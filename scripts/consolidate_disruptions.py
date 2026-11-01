"""One-time non-destructive migration for duplicate ACTIVE disruption episodes.

Run from project root:
    python scripts/consolidate_disruptions.py         # dry run
    python scripts/consolidate_disruptions.py --apply # SQLite backup + consolidate

Never deletes disruptions, carrier_events, recovery plans, impacts or the audit.
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import sys

# Allow `python scripts/consolidate_disruptions.py` from project root on Windows.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from disruption_iq import engine as e


def episode_key(row: dict) -> tuple:
    kind = row["kind"]
    if kind == "CARRIER_DELAY":
        return kind, row["shipment_id"]
    if kind == "SUPPLIER_DELAY":
        return kind, row["supplier_id"]
    if kind == "STOCK_SHORTAGE":
        return kind, row["warehouse_id"], row["sku"]
    raise ValueError(f"Unexpected disruption kind: {kind}")


def find_duplicate_groups(con: sqlite3.Connection) -> list[tuple[tuple, list[dict]]]:
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for row in e.rows(con, "SELECT * FROM disruptions WHERE status='ACTIVE' ORDER BY id"):
        buckets[episode_key(row)].append(row)
    return [(key, group) for key, group in buckets.items() if len(group) > 1]


def choose_keeper(con: sqlite3.Connection, group: list[dict]) -> dict:
    """Prefer an incident with EXECUTED or APPROVED plans to preserve its lineage.

    Other linked plans still survive even if their incident becomes SUPERSEDED.
    """
    ranks = {"EXECUTED": 0, "APPROVED": 1, "PENDING_MANAGER_APPROVAL": 2,
             "CHANGES_REQUESTED": 3, "REJECTED": 4, "CANCELLED": 5}
    def score(row: dict) -> tuple:
        states = e.rows(con, "SELECT state FROM plans WHERE disruption_id=?", (row["id"],))
        return (min((ranks.get(s["state"], 6) for s in states), default=6), row["id"])
    return min(group, key=score)


def apply_consolidation(con: sqlite3.Connection) -> list[dict]:
    """Caller MUST hold BEGIN IMMEDIATE; all modifications are transactional."""
    updates = []
    for key, group in find_duplicate_groups(con):
        keep = choose_keeper(con, group)
        archived = [row["id"] for row in group if row["id"] != keep["id"]]
        for old_id in archived:
            con.execute("UPDATE disruptions SET status='SUPERSEDED' WHERE id=? AND status='ACTIVE'", (old_id,))
        if key[0] == "SUPPLIER_DELAY":
            supplier = e.one(con, "SELECT delay_days FROM suppliers WHERE id=?", (key[1],))
            if supplier:
                con.execute("UPDATE disruptions SET detail=? WHERE id=?", (
                    f"Confirmed +{supplier['delay_days']} days beyond planned arrival", keep["id"]))
        elif key[0] == "STOCK_SHORTAGE":
            # Store the latest description on the surviving card. Historic
            # per-count adjustments remain in the audit ledger.
            newest = max(group, key=lambda row: row["id"])
            con.execute("UPDATE disruptions SET detail=? WHERE id=?", (newest["detail"], keep["id"]))
        elif key[0] == "CARRIER_DELAY":
            ship = e.one(con, """SELECT sh.carrier,sh.eta,po.due_at
                FROM shipments sh JOIN purchase_orders po ON po.id=sh.po_id
                WHERE sh.id=?""", (key[1],))
            if ship:
                # Show original PO commitment, not the previous event's ETA.
                committed = e.as_dt(ship["due_at"])
                latest = e.as_dt(ship["eta"])
                con.execute("UPDATE disruptions SET detail=? WHERE id=?", (
                    f"Carrier {ship['carrier']}: {committed:%Y-%m-%d} → {latest:%Y-%m-%d}",keep["id"]))
        e.audit(con,None,"DUPLICATE_DISRUPTIONS_CONSOLIDATED","disruption",keep["id"],
                {"episode":key,"kept_disruption":keep["id"],"superseded_disruptions":archived,
                 "note":"No events, plans, impacts or audit rows deleted"})
        updates.append({"episode":key,"kept":keep["id"],"superseded":archived})

    # Database-enforced single ACTIVE incident per affected physical entity.
    con.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_active_carrier_ship
        ON disruptions(shipment_id)
        WHERE kind='CARRIER_DELAY' AND status='ACTIVE' AND shipment_id IS NOT NULL""")
    con.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_active_supplier
        ON disruptions(supplier_id)
        WHERE kind='SUPPLIER_DELAY' AND status='ACTIVE' AND supplier_id IS NOT NULL""")
    con.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_active_stock_wh_sku
        ON disruptions(warehouse_id, sku)
        WHERE kind='STOCK_SHORTAGE' AND status='ACTIVE'
          AND warehouse_id IS NOT NULL AND sku IS NOT NULL""")
    return updates


def make_backup() -> Path:
    src = e.DB_PATH.resolve()
    if not src.is_file():
        raise FileNotFoundError(f"Database not found: {src}")
    when = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    destination = src.with_name(f"{src.stem}.before-dedupe-{when}.sqlite3")
    with sqlite3.connect(src) as origin, sqlite3.connect(destination) as backup:
        origin.backup(backup)
    return destination


def main():
    parser = argparse.ArgumentParser(description="Consolidate repeated ACTIVE logistics alerts without deleting history")
    parser.add_argument("--apply", action="store_true", help="Back up database then archive repeated active incidents")
    args = parser.parse_args()
    if not e.DB_PATH.is_file():
        raise SystemExit(f"Database not found: {e.DB_PATH}. Run from the project root.")
    with e.read_db() as c:
        groups = find_duplicate_groups(c)
        print(f"Database: {e.DB_PATH.resolve()}")
        print(f"Repeated active incident groups: {len(groups)}")
        for key, entries in groups:
            keeper = choose_keeper(c, entries)
            print(f"  {key}: active IDs {[r['id'] for r in entries]} -> keep {keeper['id']}")
            plan_counts = {r["id"]:e.one(c,"SELECT count(*) n FROM plans WHERE disruption_id=?",(r["id"],))["n"]
                           for r in entries}
            print(f"      Linked recovery plans per ID: {plan_counts} (all preserved)")
    if not args.apply:
        print("DRY RUN: Nothing changed. Stop Reflex then rerun with --apply to consolidate.")
        return
    backup=make_backup()
    print(f"SQLite backup created: {backup}")
    with e.tx() as c:
        updates=apply_consolidation(c)
    print(f"Consolidated {len(updates)} active incident groups; archived {sum(len(g['superseded']) for g in updates)} repeated cards.")
    print("Historical webhook events, impacts, recovery plans and audit records were preserved.")
    print("Restart Reflex and click SYNC.")


if __name__ == "__main__":
    main()
