"""DisruptionIQ deterministic domain engine: SQLite, lineage, RBAC, dual control.

No frontend-supplied role, score, inventory balance, or status is trusted.
All mutations use transactions and backend authorization.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("DISRUPTION_DB", str(ROOT / "disruption_iq.sqlite3")))
_WRITE_LOCK = threading.RLock()
MAX_IMPORT_BYTES = 2_000_000
ROLES = ("Operations Analyst", "Supply Chain Manager", "Warehouse Operator", "Procurement Approver", "Administrator")
APPROVERS = {"REORDER": "Procurement Approver", "REALLOCATE": "Supply Chain Manager",
             "EXPEDITE": "Supply Chain Manager", "SPLIT": "Supply Chain Manager"}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def days_from_today(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat()


def as_dt(text: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timezone is required")
        return parsed.astimezone(timezone.utc)
    except Exception as exc:
        raise ValueError(f"Invalid ISO-8601 timestamp: {text}") from exc


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=20000")
    con.execute("PRAGMA journal_mode=WAL")
    return con


@contextmanager
def tx():
    with _WRITE_LOCK:
        con = connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()


@contextmanager
def read_db():
    """Read-only scoped connection. sqlite's context manager alone does not close it."""
    con=connect()
    try:
        yield con
    finally:
        con.close()


def one(con: sqlite3.Connection, sql: str, args: tuple = ()) -> dict | None:
    r = con.execute(sql, args).fetchone()
    return dict(r) if r else None


def rows(con: sqlite3.Connection, sql: str, args: tuple = ()) -> list[dict]:
    return [dict(x) for x in con.execute(sql, args).fetchall()]


def must(condition: bool, message: str):
    if not condition:
        raise ValueError(message)


def password_hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 260_000).hex()


def actor(con: sqlite3.Connection, user_id: int, allowed: tuple[str, ...] | None = None) -> dict:
    user = one(con, "SELECT id,username,display_name,role FROM users WHERE id=? AND enabled=1", (user_id,))
    if not user:
        raise PermissionError("Authentication required")
    if allowed is not None and user["role"] not in allowed:
        raise PermissionError(f"Permission denied: role {user['role']} cannot perform this action")
    return user


def login(username: str, password: str) -> dict:
    with read_db() as con:
        r = one(con, "SELECT * FROM users WHERE username=? AND enabled=1", (username.strip().lower(),))
        if not r or not hmac.compare_digest(password_hash(password, r["salt"]), r["password_hash"]):
            raise PermissionError("Invalid username or password")
        return {k:r[k] for k in ("id", "username", "display_name", "role")}


def audit(con, uid, action, entity, entity_id, detail):
    con.execute("INSERT INTO audit(actor_id,action,entity_type,entity_id,detail,created_at) VALUES (?,?,?,?,?,?)",
                (uid, action, entity, str(entity_id), json.dumps(detail, sort_keys=True, default=str), now()))


def notify(con, roles: tuple[str, ...], message: str):
    for u in rows(con, f"SELECT id FROM users WHERE role IN ({','.join('?' for _ in roles)}) AND enabled=1", roles):
        con.execute("INSERT INTO notifications(user_id,message,created_at) VALUES (?,?,?)", (u["id"], message, now()))


DDL = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('Operations Analyst','Supply Chain Manager','Warehouse Operator','Procurement Approver','Administrator')),
 salt TEXT NOT NULL, password_hash TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS suppliers(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, reliability INTEGER NOT NULL CHECK(reliability BETWEEN 0 AND 100),
 lead_days INTEGER NOT NULL CHECK(lead_days>=1), delay_days INTEGER NOT NULL DEFAULT 0 CHECK(delay_days>=0), status TEXT NOT NULL DEFAULT 'ACTIVE');
CREATE TABLE IF NOT EXISTS supplier_skus(supplier_id INTEGER NOT NULL REFERENCES suppliers(id), sku TEXT NOT NULL,
 PRIMARY KEY(supplier_id,sku));
CREATE TABLE IF NOT EXISTS supplier_sku_capacity(supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
 sku TEXT NOT NULL,capacity_units INTEGER NOT NULL CHECK(capacity_units>=0),
 committed_units INTEGER NOT NULL DEFAULT 0 CHECK(committed_units>=0 AND committed_units<=capacity_units),
 PRIMARY KEY(supplier_id,sku));
CREATE TABLE IF NOT EXISTS warehouses(id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, region TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS inventory(id INTEGER PRIMARY KEY, warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
 sku TEXT NOT NULL, on_hand INTEGER NOT NULL CHECK(on_hand>=0), reserved INTEGER NOT NULL DEFAULT 0 CHECK(reserved>=0 AND reserved<=on_hand),
 safety_stock INTEGER NOT NULL DEFAULT 0 CHECK(safety_stock>=0), UNIQUE(warehouse_id,sku));
CREATE TABLE IF NOT EXISTS purchase_orders(id INTEGER PRIMARY KEY, po_no TEXT NOT NULL UNIQUE, supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
 sku TEXT NOT NULL, qty INTEGER NOT NULL CHECK(qty>0), warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
 due_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN');
CREATE TABLE IF NOT EXISTS shipments(id INTEGER PRIMARY KEY, tracking TEXT NOT NULL UNIQUE, carrier TEXT NOT NULL,
 vessel TEXT NOT NULL, po_id INTEGER NOT NULL UNIQUE REFERENCES purchase_orders(id), eta TEXT NOT NULL,
 updated_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'IN_TRANSIT', carrier_revision INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, order_no TEXT NOT NULL UNIQUE, customer TEXT NOT NULL, sku TEXT NOT NULL,
 qty INTEGER NOT NULL CHECK(qty>0), warehouse_id INTEGER NOT NULL REFERENCES warehouses(id), priority TEXT NOT NULL
 CHECK(priority IN ('STANDARD','HIGH','CRITICAL')), sla_due TEXT NOT NULL, value REAL NOT NULL CHECK(value>=0),
 status TEXT NOT NULL DEFAULT 'OPEN');
CREATE TABLE IF NOT EXISTS disruptions(id INTEGER PRIMARY KEY, source TEXT NOT NULL, event_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('CARRIER_DELAY','SUPPLIER_DELAY','STOCK_SHORTAGE')),
 title TEXT NOT NULL, shipment_id INTEGER REFERENCES shipments(id), supplier_id INTEGER REFERENCES suppliers(id),
 warehouse_id INTEGER REFERENCES warehouses(id), sku TEXT, detail TEXT NOT NULL, severity TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'ACTIVE', created_at TEXT NOT NULL, UNIQUE(source,event_id));
CREATE TABLE IF NOT EXISTS impacts(id INTEGER PRIMARY KEY, disruption_id INTEGER NOT NULL REFERENCES disruptions(id),
 order_id INTEGER NOT NULL REFERENCES orders(id), score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 100),
 short_units INTEGER NOT NULL, explanation TEXT NOT NULL, UNIQUE(disruption_id,order_id));
CREATE TABLE IF NOT EXISTS carrier_events(id INTEGER PRIMARY KEY, source TEXT NOT NULL, event_id TEXT NOT NULL,
 shipment_id INTEGER NOT NULL REFERENCES shipments(id), revision INTEGER NOT NULL, hash TEXT NOT NULL,
 outcome TEXT NOT NULL, occurred_at TEXT NOT NULL, received_at TEXT NOT NULL, UNIQUE(source,event_id));
CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY, disruption_id INTEGER NOT NULL REFERENCES disruptions(id),
 order_id INTEGER NOT NULL REFERENCES orders(id), kind TEXT NOT NULL,
 qty INTEGER NOT NULL CHECK(qty>0), source_warehouse_id INTEGER REFERENCES warehouses(id),
 supplier_id INTEGER REFERENCES suppliers(id), estimate_cost REAL NOT NULL CHECK(estimate_cost>=0),
 eta_days INTEGER NOT NULL, rationale TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
 state TEXT NOT NULL CHECK(state IN ('PENDING_MANAGER_APPROVAL','CHANGES_REQUESTED','REJECTED','APPROVED','EXECUTED','CANCELLED')),
 proposed_by INTEGER NOT NULL REFERENCES users(id), decided_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL, decided_at TEXT, executed_at TEXT, version INTEGER NOT NULL DEFAULT 1,
 CHECK(version>=1));
CREATE TABLE IF NOT EXISTS optimization_runs(id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
 proposed_by INTEGER NOT NULL REFERENCES users(id), profile TEXT NOT NULL, budget REAL NOT NULL,
 transport_limit INTEGER NOT NULL,signature TEXT NOT NULL,scenario_json TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'SUBMITTED');
CREATE INDEX IF NOT EXISTS idx_optimization_runs_by ON optimization_runs(proposed_by,created_at);
CREATE TABLE IF NOT EXISTS fulfillment_tasks(id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL REFERENCES plans(id),
 order_id INTEGER NOT NULL REFERENCES orders(id), warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
 qty INTEGER NOT NULL CHECK(qty>0), status TEXT NOT NULL DEFAULT 'PENDING', created_at TEXT NOT NULL,
 completed_at TEXT);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 message TEXT NOT NULL, created_at TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, actor_id INTEGER REFERENCES users(id), action TEXT NOT NULL,
 entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_orders_sku_wh ON orders(sku,warehouse_id,sla_due);
CREATE INDEX IF NOT EXISTS idx_impacts_order ON impacts(order_id);
CREATE INDEX IF NOT EXISTS idx_plans_state ON plans(state);
"""


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with read_db() as c:
        c.executescript(DDL)
        # Works on existing v1.8 databases without dropping tables or orders.
        existing={row['name'] for row in c.execute('PRAGMA table_info(plans)')}
        if 'optimization_run_id' not in existing:
            c.execute('ALTER TABLE plans ADD COLUMN optimization_run_id INTEGER REFERENCES optimization_runs(id)')
        c.execute("""INSERT OR IGNORE INTO supplier_sku_capacity(supplier_id,sku,capacity_units)
                     SELECT supplier_id,sku,80 FROM supplier_skus""")
    seed_if_empty()
    # Seed was empty before first launch; install synthetic supplier capacity.
    with read_db() as c:
        c.execute("""INSERT OR IGNORE INTO supplier_sku_capacity(supplier_id,sku,capacity_units)
                     SELECT supplier_id,sku,80 FROM supplier_skus""")


def seed_if_empty():
    with tx() as c:
        if one(c, "SELECT id FROM users LIMIT 1"):
            return
        accounts = [
            ("analyst", "Asha Rao", "Operations Analyst", "Analyst#2026"),
            ("manager", "Marcus Chen", "Supply Chain Manager", "Manager#2026"),
            ("warehouse", "Nila Iyer", "Warehouse Operator", "Warehouse#2026"),
            ("procurement", "Leena Shah", "Procurement Approver", "Procure#2026"),
            ("admin", "System Admin", "Administrator", "Admin#2026"),
        ]
        for username, name, role, passwd in accounts:
            salt = secrets.token_hex(16)
            c.execute("INSERT INTO users(username,display_name,role,salt,password_hash) VALUES (?,?,?,?,?)",
                      (username,name,role,salt,password_hash(passwd,salt)))
        c.executemany("INSERT INTO suppliers(id,name,reliability,lead_days,status) VALUES (?,?,?,?,?)", [
            (1,"Aster Components",91,4,"ACTIVE"),(2,"Pacific Cells Co.",73,6,"ACTIVE"),
            (3,"Northstar Industrial",96,3,"ACTIVE"),(4,"Horizon Materials",86,5,"ACTIVE")])
        c.executemany("INSERT INTO supplier_skus(supplier_id,sku) VALUES (?,?)", [
            (1,"SENSOR-X"),(3,"SENSOR-X"),(2,"BATTERY-M"),(4,"BATTERY-M"),(1,"VALVE-K"),(3,"VALVE-K")])
        c.executemany("INSERT INTO warehouses(id,code,name,region) VALUES (?,?,?,?)", [
            (1,"BLR-01","Bengaluru Fulfilment","South"),(2,"MUM-02","Mumbai Gateway","West"),
            (3,"DEL-03","Delhi Distribution","North")])
        c.executemany("INSERT INTO inventory(warehouse_id,sku,on_hand,reserved,safety_stock) VALUES (?,?,?,?,?)", [
            (1,"SENSOR-X",42,18,18),(2,"SENSOR-X",130,16,25),(3,"SENSOR-X",10,4,10),
            (1,"BATTERY-M",22,10,15),(2,"BATTERY-M",26,12,18),(3,"BATTERY-M",28,17,15),
            (1,"VALVE-K",150,38,30),(2,"VALVE-K",19,6,10),(3,"VALVE-K",75,18,20)])
        c.executemany("INSERT INTO purchase_orders(id,po_no,supplier_id,sku,qty,warehouse_id,due_at) VALUES (?,?,?,?,?,?,?)", [
            (1,"PO-8401",1,"SENSOR-X",125,1,days_from_today(2)),
            (2,"PO-8402",2,"BATTERY-M",110,3,days_from_today(3)),
            (3,"PO-8403",1,"VALVE-K",65,2,days_from_today(5)),
            (4,"PO-8404",3,"SENSOR-X",80,3,days_from_today(4))])
        c.executemany("INSERT INTO shipments(id,tracking,carrier,vessel,po_id,eta,updated_at) VALUES (?,?,?,?,?,?,?)", [
            (1,"SHP-1001","Mariner Global","Container Ship X",1,days_from_today(2),now()),
            (2,"SHP-1002","SwiftFreight","Pacific Voyager",2,days_from_today(3),now()),
            (3,"SHP-1003","BlueWing Cargo","Northern Star",3,days_from_today(5),now()),
            (4,"SHP-1004","Mariner Global","Eastern Current",4,days_from_today(4),now())])
        c.executemany("INSERT INTO orders(id,order_no,customer,sku,qty,warehouse_id,priority,sla_due,value) VALUES (?,?,?,?,?,?,?,?,?)", [
            (1,"ORD-90241","Atlas Aerospace","SENSOR-X",58,1,"CRITICAL",days_from_today(3),240000),
            (2,"ORD-90242","Meridian Medical","SENSOR-X",45,1,"HIGH",days_from_today(5),138000),
            (3,"ORD-90243","Polar Automotive","BATTERY-M",67,3,"CRITICAL",days_from_today(4),196000),
            (4,"ORD-90244","Orion Devices","BATTERY-M",35,3,"HIGH",days_from_today(6),76000),
            (5,"ORD-90245","Kinetic Labs","VALVE-K",32,2,"STANDARD",days_from_today(7),21000),
            (6,"ORD-90246","Northwind Robotics","SENSOR-X",28,3,"HIGH",days_from_today(6),82000),
            (7,"ORD-90247","Vega Energy","VALVE-K",44,1,"HIGH",days_from_today(2),94000),
            (8,"ORD-90248","Helix Systems","SENSOR-X",25,1,"STANDARD",days_from_today(8),28000)])
        audit(c,None,"SEED","system",1,{"description":"Synthetic demo data initialized"})


def ensure_iso(value):
    as_dt(str(value))
    return str(value)


def positive_int(value, label):
    try:
        must(not isinstance(value,bool),f"{label} must be a positive integer")
        num=int(value)
        must(str(value).strip() not in ("", "None") and num>0 and float(value)==num, f"{label} must be a positive integer")
        return num
    except (TypeError,ValueError,OverflowError) as e:
        raise ValueError(f"{label} must be a positive integer") from e


def nonnegative_int(value,label):
    try:
        must(not isinstance(value,bool),f"{label} must be a nonnegative integer")
        num=int(value)
        must(num>=0 and float(value)==num,f"{label} must be a nonnegative integer")
        return num
    except (TypeError,ValueError,OverflowError) as e:
        raise ValueError(f"{label} must be a nonnegative integer") from e


def ingest_carrier(payload: dict[str, Any], source: str = "mariner") -> dict:
    """Apply monotonic carrier revisions and maintain ONE active delay per shipment.

    Every distinct webhook is retained in carrier_events, even when an update is
    unchanged.  Its event_id provides idempotence; its revision prevents stale
    updates.  Active incidents represent *episodes*, not event messages.
    """
    must(isinstance(payload,dict), "Webhook must be a JSON object")
    required={"event_id", "tracking", "revision", "eta", "occurred_at"}
    must(required.issubset(payload), "Missing carrier event fields")
    event_id=str(payload["event_id"]).strip(); tracking=str(payload["tracking"]).strip()
    must(0<len(event_id)<=100 and 0<len(tracking)<=60, "Invalid event ID or tracking")
    revision=positive_int(payload["revision"], "revision")
    eta=ensure_iso(payload["eta"]); occurred=ensure_iso(payload["occurred_at"])
    must(abs((as_dt(occurred)-datetime.now(timezone.utc)).total_seconds())<86400*90,
         "Event timestamp outside 90-day window")
    normalized={"event_id":event_id, "tracking":tracking, "revision":revision,
                "eta":as_dt(eta).isoformat(), "occurred_at":as_dt(occurred).isoformat()}
    digest=hashlib.sha256(json.dumps(normalized,sort_keys=True).encode()).hexdigest()
    with tx() as c:
        old=one(c,"SELECT * FROM carrier_events WHERE source=? AND event_id=?",(source,event_id))
        if old:
            if old["hash"] == digest:
                return {"outcome":"DUPLICATE", "disruption_id":None, "affected":0}
            raise ValueError("Conflicting duplicate event ID: event rejected")
        shipment=one(c,"SELECT * FROM shipments WHERE tracking=?",(tracking,))
        must(shipment is not None,"Unknown tracking number")
        if revision <= shipment["carrier_revision"]:
            c.execute("""INSERT INTO carrier_events
                (source,event_id,shipment_id,revision,hash,outcome,occurred_at,received_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (source,event_id,shipment["id"],revision,digest,"STALE_IGNORED",occurred,now()))
            audit(c,None,"WEBHOOK_STALE","shipment",shipment["id"],
                  {"event_id":event_id,"revision":revision})
            return {"outcome":"STALE_IGNORED","disruption_id":None,"affected":0}
        if as_dt(occurred) < as_dt(shipment["updated_at"])-timedelta(minutes=1):
            raise ValueError("Conflicting older carrier timestamp")

        previous_eta=as_dt(shipment["eta"])
        updated_eta=as_dt(eta)
        baseline=one(c,"SELECT due_at FROM purchase_orders WHERE id=?",(shipment["po_id"],))
        must(baseline is not None, "Shipment purchase order not found")
        promised=as_dt(baseline["due_at"])
        is_late=updated_eta>promised
        changed=updated_eta!=previous_eta

        # Do not let a newer revision with an unchanged ETA become a new incident.
        c.execute("""UPDATE shipments SET eta=?,carrier_revision=?,updated_at=?,status=? WHERE id=?""",
                  (eta,revision,occurred,"DELAYED" if is_late else "IN_TRANSIT",shipment["id"]))
        c.execute("""INSERT INTO carrier_events
            (source,event_id,shipment_id,revision,hash,outcome,occurred_at,received_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (source,event_id,shipment["id"],revision,digest,
             "APPLIED" if changed else "NO_CHANGE",occurred,now()))
        active=one(c,"""SELECT id FROM disruptions
            WHERE kind='CARRIER_DELAY' AND shipment_id=? AND status='ACTIVE'
            ORDER BY id LIMIT 1""",(shipment["id"],))
        if not is_late:
            if active:
                c.execute("""UPDATE disruptions SET status='RESOLVED' WHERE
                    kind='CARRIER_DELAY' AND shipment_id=? AND status='ACTIVE'""",
                    (shipment["id"],))
                audit(c,None,"CARRIER_DELAY_RESOLVED","shipment",shipment["id"],
                      {"event_id":event_id,"resolved_ids":active["id"],"eta":eta})
                notify(c,("Operations Analyst","Supply Chain Manager"),
                       f"Carrier update: {shipment['vessel']} back within committed ETA")
            recompute_all_active_impacts(c)
            return {"outcome":"RESOLVED" if active else "APPLIED_NO_DELAY",
                    "disruption_id":active["id"] if active else None,"affected":0}
        if not changed:
            audit(c,None,"WEBHOOK_NO_CHANGE","shipment",shipment["id"],
                  {"event_id":event_id,"revision":revision,"eta":eta})
            return {"outcome":"NO_CHANGE",
                    "disruption_id":active["id"] if active else None,
                    "affected":one(c,"SELECT count(*) n FROM impacts WHERE disruption_id=?",
                                   (active["id"],))["n"] if active else 0}

        # Compare against the *contracted* PO ETA, not against the previous
        # carrier message, which may already have reported this same delay.
        detail=f"Carrier {shipment['carrier']}: {promised:%Y-%m-%d} → {updated_eta:%Y-%m-%d}"
        if active:
            disruption_id=active["id"]
            c.execute("UPDATE disruptions SET detail=? WHERE id=?",(detail,disruption_id))
            event_action="CARRIER_DELAY_UPDATED"
            outcome="UPDATED"
        else:
            cur=c.execute("""INSERT INTO disruptions
                (source,event_id,kind,title,shipment_id,detail,severity,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (source,event_id,"CARRIER_DELAY",f"{shipment['vessel']} · ETA slipped",
                 shipment["id"],detail,"CRITICAL",now()))
            disruption_id=cur.lastrowid
            event_action="CARRIER_DELAY"
            outcome="APPLIED"
        recompute_all_active_impacts(c)
        affected=one(c,"SELECT count(*) n FROM impacts WHERE disruption_id=?",(disruption_id,))["n"]
        audit(c,None,event_action,"shipment",shipment["id"],
              {"event_id":event_id,"revision":revision,"affected_orders":affected,
               "disruption_id":disruption_id})
        notify(c,("Operations Analyst","Supply Chain Manager"),
               f"Carrier alert: {shipment['vessel']} updated, {affected} orders in lineage")
        return {"outcome":outcome,"disruption_id":disruption_id,"affected":affected}


def simulate_supplier_delay(uid: int, supplier_id: int, days: int, event_id: str | None = None) -> dict:
    days=positive_int(days,"delay days")
    must(days<=60,"Delay must be <=60 days")
    event_id=event_id or f"supplier-{secrets.token_hex(7)}"
    with tx() as c:
        actor(c,uid,("Operations Analyst","Supply Chain Manager","Administrator"))
        supplier=one(c,"SELECT * FROM suppliers WHERE id=?",(supplier_id,))
        must(supplier is not None,"Supplier not found")
        existing_event=one(c,"""SELECT * FROM disruptions
            WHERE source='supplier-sim' AND event_id=?""",(event_id,))
        if existing_event:
            return {"outcome":"DUPLICATE","disruption_id":existing_event["id"],"affected":0}
        active=one(c,"""SELECT id FROM disruptions WHERE kind='SUPPLIER_DELAY'
            AND supplier_id=? AND status='ACTIVE' ORDER BY id LIMIT 1""",(supplier_id,))
        if active and supplier["delay_days"]==days:
            return {"outcome":"NO_CHANGE","disruption_id":active["id"],
                    "affected":one(c,"SELECT count(*) n FROM impacts WHERE disruption_id=?",
                                   (active["id"],))["n"]}
        c.execute("UPDATE suppliers SET delay_days=? WHERE id=?",(days,supplier_id))
        detail=f"Confirmed +{days} days beyond planned arrival"
        if active:
            disruption_id=active["id"]
            c.execute("UPDATE disruptions SET detail=? WHERE id=?",(detail,disruption_id))
            event_action="SUPPLIER_DELAY_UPDATED"
            outcome="UPDATED"
        else:
            cur=c.execute("""INSERT INTO disruptions
                (source,event_id,kind,title,supplier_id,detail,severity,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                ("supplier-sim",event_id,"SUPPLIER_DELAY",
                 supplier["name"]+" · production delay",supplier_id,detail,"HIGH",now()))
            disruption_id=cur.lastrowid
            event_action="SUPPLIER_DELAY"
            outcome="APPLIED"
        recompute_all_active_impacts(c)
        affected=one(c,"SELECT count(*) n FROM impacts WHERE disruption_id=?",(disruption_id,))["n"]
        audit(c,uid,event_action,"supplier",supplier_id,
              {"days":days,"affected_orders":affected,"disruption_id":disruption_id})
        notify(c,("Operations Analyst","Supply Chain Manager","Procurement Approver"),
               f"Supplier delay: {supplier['name']}, {affected} orders affected")
        return {"outcome":outcome,"affected":affected,"disruption_id":disruption_id}


def simulate_stock_shortage(uid: int, wh_id: int, sku: str, lost_units: int) -> dict:
    """A new confirmed stock adjustment, attached to one ongoing shortage incident."""
    lost_units=positive_int(lost_units,"lost units")
    with tx() as c:
        actor(c,uid,("Operations Analyst","Warehouse Operator","Administrator"))
        stock=one(c,"SELECT * FROM inventory WHERE warehouse_id=? AND sku=?",(wh_id,sku))
        must(stock is not None,"Stock record does not exist")
        must(stock["on_hand"]-lost_units>=stock["reserved"],
             "Cannot reduce stock below reserved allocations")
        c.execute("UPDATE inventory SET on_hand=on_hand-? WHERE id=?",(lost_units,stock["id"]))
        active=one(c,"""SELECT id FROM disruptions WHERE kind='STOCK_SHORTAGE'
            AND warehouse_id=? AND sku=? AND status='ACTIVE' ORDER BY id LIMIT 1""",
            (wh_id,sku))
        if active:
            disruption_id=active["id"]
            # The audit stores every physical adjustment. The incident is a
            # single ongoing warehouse/SKU shortage, not one card per count.
            c.execute("UPDATE disruptions SET detail=? WHERE id=?",
                      (f"Latest reconciliation removed {lost_units} units; see audit for full history",
                       disruption_id))
            outcome="UPDATED"
        else:
            eid=f"stock-{secrets.token_hex(7)}"
            cur=c.execute("""INSERT INTO disruptions
                (source,event_id,kind,title,warehouse_id,sku,detail,severity,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                ("warehouse-sim",eid,"STOCK_SHORTAGE",f"{sku} · cycle count variance",
                 wh_id,sku,f"Physical reconciliation removed {lost_units} units","HIGH",now()))
            disruption_id=cur.lastrowid
            outcome="APPLIED"
        recompute_all_active_impacts(c)
        affected=one(c,"SELECT count(*) n FROM impacts WHERE disruption_id=?",(disruption_id,))["n"]
        audit(c,uid,"STOCK_SHORTAGE","inventory",stock["id"],
              {"lost":lost_units,"affected_orders":affected,"disruption_id":disruption_id})
        notify(c,("Operations Analyst","Supply Chain Manager","Warehouse Operator"),
               f"Inventory variance: {sku}; {affected} customer orders impacted")
        return {"outcome":outcome,"affected":affected,"disruption_id":disruption_id}


def projection(con, order: dict) -> dict:
    """FIFO/SLA cumulative demand with inbound by deadline; no probabilistic inventory arithmetic."""
    inv=one(con,"SELECT on_hand,reserved,safety_stock FROM inventory WHERE warehouse_id=? AND sku=?",
            (order["warehouse_id"],order["sku"])) or {"on_hand":0,"reserved":0,"safety_stock":0}
    available=max(0,inv["on_hand"]-inv["reserved"]-inv["safety_stock"])
    due=as_dt(order["sla_due"])
    predecessors=one(con,"""SELECT COALESCE(SUM(qty),0) AS qty FROM orders
         WHERE warehouse_id=? AND sku=? AND status NOT IN ('FULFILLED','CANCELLED')
         AND (sla_due < ? OR (sla_due=? AND id<=?))""",
         (order["warehouse_id"],order["sku"],order["sla_due"],order["sla_due"],order["id"]))["qty"]
    inbound=rows(con,"""SELECT po.qty,po.due_at,po.status, s.delay_days,sh.eta,sh.status AS shipment_status
       FROM purchase_orders po JOIN suppliers s ON s.id=po.supplier_id
       LEFT JOIN shipments sh ON sh.po_id=po.id
       WHERE po.warehouse_id=? AND po.sku=? AND po.status='OPEN'""",(order["warehouse_id"],order["sku"]))
    eligible=0; late=0; late_names=[]
    for po in inbound:
        base=max(as_dt(po["due_at"]),as_dt(po["eta"])) if po["eta"] else as_dt(po["due_at"])
        expected=base+timedelta(days=po["delay_days"])
        if expected<=due:
            eligible+=po["qty"]
        else:
            late+=po["qty"]
            late_names.append(f"{(expected-due).days+1}d behind SLA")
    gap=max(0,predecessors-available-eligible)
    gap_for_order=min(order["qty"],gap)
    return {"available":available,"eligible_inbound":eligible,"late_inbound":late,"short_units":gap_for_order,
            "cumulative_demand":predecessors,"safety_stock":inv["safety_stock"],"late_detail":", ".join(late_names),
            "days_to_sla":(due-datetime.now(timezone.utc)).total_seconds()/86400}


def candidate_orders(con, disruption: dict) -> list[dict]:
    if disruption["kind"]=="CARRIER_DELAY":
        return rows(con,"""SELECT o.* FROM orders o JOIN purchase_orders po
          ON po.sku=o.sku AND po.warehouse_id=o.warehouse_id
          JOIN shipments sh ON sh.po_id=po.id WHERE sh.id=? AND o.status NOT IN ('FULFILLED','CANCELLED')""",
          (disruption["shipment_id"],))
    if disruption["kind"]=="SUPPLIER_DELAY":
        return rows(con,"""SELECT DISTINCT o.* FROM orders o JOIN purchase_orders po
           ON po.sku=o.sku AND po.warehouse_id=o.warehouse_id
           WHERE po.supplier_id=? AND o.status NOT IN ('FULFILLED','CANCELLED')""",(disruption["supplier_id"],))
    return rows(con,"SELECT * FROM orders WHERE warehouse_id=? AND sku=? AND status NOT IN ('FULFILLED','CANCELLED')",
                (disruption["warehouse_id"],disruption["sku"]))


def recompute_impacts(con, disruption_id: int) -> int:
    disruption=one(con,"SELECT * FROM disruptions WHERE id=?",(disruption_id,))
    must(disruption is not None,"Disruption not found")
    con.execute("DELETE FROM impacts WHERE disruption_id=?",(disruption_id,))
    count=0
    for order in candidate_orders(con,disruption):
        p=projection(con,order)
        if p["short_units"]<=0:
            continue
        urgency=30 if p["days_to_sla"]<2 else 20 if p["days_to_sla"]<5 else 6
        value_factor=22 if order["value"]>=150000 else 12 if order["value"]>=75000 else 3
        priority_factor={"CRITICAL":20,"HIGH":12,"STANDARD":4}[order["priority"]]
        shortage_factor=round(28*p["short_units"]/order["qty"])
        score=min(100,urgency+value_factor+priority_factor+shortage_factor)
        detail=(f"{p['short_units']}/{order['qty']} units at risk; available {p['available']}, "
          f"incoming before SLA {p['eligible_inbound']}; {p['days_to_sla']:.1f} days to deadline; "
          f"{order['priority'].lower()} priority; ${order['value']:,.0f} contract. "
          f"Risk factors: shortage {shortage_factor}/28, urgency {urgency}/30, "
          f"value {value_factor}/22, SLA priority {priority_factor}/20.")
        con.execute("""INSERT INTO impacts(disruption_id,order_id,score,short_units,explanation) VALUES (?,?,?,?,?)
           ON CONFLICT(disruption_id,order_id) DO UPDATE SET score=excluded.score,short_units=excluded.short_units,
           explanation=excluded.explanation""",(disruption_id,order["id"],score,p["short_units"],detail))
        count+=1
    return count


def recompute_all_active_impacts(con):
    """Refresh affected-order view after any confirmed stock/ETA or status change."""
    for disruption in rows(con,"SELECT id FROM disruptions WHERE status='ACTIVE'"):
        recompute_impacts(con,disruption["id"])


def recovery_options(con, disruption_id: int, order_id: int) -> list[dict]:
    incident=one(con,"SELECT status FROM disruptions WHERE id=?",(disruption_id,))
    must(incident is not None and incident["status"] == "ACTIVE",
         "Recovery actions require an active disruption")
    impact=one(con,"SELECT * FROM impacts WHERE disruption_id=? AND order_id=?",(disruption_id,order_id))
    must(impact is not None,"Order is not affected by that disruption")
    o=one(con,"SELECT * FROM orders WHERE id=?",(order_id,))
    # A recovering or closed order must not receive another recovery plan.
    if o["status"] in ("RECOVERY_IN_PROGRESS", "FULFILLED", "CANCELLED"):
        return []
    p=projection(con,o)
    gap=max(1,p["short_units"])
    options=[]
    for inv in rows(con,"SELECT i.warehouse_id,w.code,MAX(0,i.on_hand-i.reserved-i.safety_stock) AS free FROM inventory i JOIN warehouses w ON w.id=i.warehouse_id WHERE i.sku=? AND i.warehouse_id<>?",(o["sku"],o["warehouse_id"])):
        if inv["free"]>=gap:
            options.append({"kind":"REALLOCATE","title":f"Reallocate from {inv['code']}","qty":gap,
                "source_warehouse_id":inv["warehouse_id"],"supplier_id":None,"eta_days":1,
                "estimate_cost":round(gap*18.0,2),"rationale":f"{inv['free']} unreserved units at {inv['code']}; transfer {gap}. Verify local SLA."})
    d=one(con,"SELECT * FROM disruptions WHERE id=?",(disruption_id,))
    sh=one(con,"""SELECT sh.* FROM shipments sh JOIN purchase_orders po ON po.id=sh.po_id
        WHERE po.sku=? AND po.warehouse_id=? AND sh.status IN ('IN_TRANSIT','DELAYED') ORDER BY sh.eta LIMIT 1""",
        (o["sku"],o["warehouse_id"]))
    if sh:
        accelerated=max(datetime.now(timezone.utc)+timedelta(days=1),as_dt(sh["eta"])-timedelta(days=3))
        # Do not suggest a freight action that cannot improve the current ETA.
        if accelerated < as_dt(sh["eta"]):
            days=max(1,(accelerated-datetime.now(timezone.utc)).days+1)
            options.append({"kind":"EXPEDITE","title":"Expedite inbound freight","qty":gap,
                 "source_warehouse_id":None,"supplier_id":None,"eta_days":days,
                 "estimate_cost":round(max(250,sh["id"]*80+gap*24),2),
                 "rationale":f"Rush {sh['tracking']}; earliest model ETA {accelerated.date()}, deterministic 3-day gain cap."})
    upstream_supplier=one(con,"""SELECT po.supplier_id FROM purchase_orders po
         JOIN shipments sh ON sh.po_id=po.id WHERE po.sku=? AND po.warehouse_id=?
         ORDER BY sh.eta LIMIT 1""",(o["sku"],o["warehouse_id"]))
    possible_suppliers=rows(con,"""SELECT s.* FROM suppliers s JOIN supplier_skus ss ON ss.supplier_id=s.id
         WHERE ss.sku=? AND s.status='ACTIVE' ORDER BY s.reliability DESC""",(o["sku"],))
    for s in possible_suppliers[:2]:
        if d["supplier_id"]==s["id"] or (upstream_supplier and upstream_supplier["supplier_id"]==s["id"]):
            continue
        capacity=one(con,"SELECT capacity_units-committed_units AS free FROM supplier_sku_capacity WHERE supplier_id=? AND sku=?",
                     (s['id'],o['sku']))
        if capacity is None or capacity['free'] < gap:
            continue
        days=s["lead_days"]+s["delay_days"]
        options.append({"kind":"REORDER","title":f"Alternative supplier: {s['name']}","qty":gap,
          "source_warehouse_id":None,"supplier_id":s["id"],"eta_days":days,
          "estimate_cost":round(gap*47+180,2),
          "rationale":f"{s['reliability']}% historical reliability; {days}-day stated lead time; PO issued only after approval."})
    dst=p["available"]
    for inv in rows(con,"SELECT warehouse_id,MAX(0,on_hand-reserved-safety_stock) AS free FROM inventory WHERE sku=? AND warehouse_id<>? ORDER BY free DESC",(o["sku"],o["warehouse_id"])):
        if dst>0 and inv["free"]>0 and dst+inv["free"]>=o["qty"]:
            options.append({"kind":"SPLIT","title":"Split fulfillment across two hubs","qty":o["qty"],
              "source_warehouse_id":inv["warehouse_id"],"supplier_id":None,"eta_days":2,
              "estimate_cost":round(o["qty"]*22+120,2),
              "rationale":f"Fulfill {dst} locally and {o['qty']-dst} from other warehouse; reserve only on confirmed execution."})
            break
    for option in options:
        eta = datetime.now(timezone.utc) + timedelta(days=option["eta_days"])
        option["meets_sla"] = eta <= as_dt(o["sla_due"])
        option["sla_note"] = ("Projected within deadline" if option["meets_sla"]
                               else "Projected after SLA: escalation required")
    return options


def record_denial(uid:int,action:str,entity_id:int,exc:Exception):
    """Denial is committed separately AFTER the failed operation rolls back."""
    try:
        with tx() as c:
            if one(c,"SELECT id FROM users WHERE id=?",(uid,)):
                audit(c,uid,"ACCESS_DENIED",action,entity_id,{"reason":str(exc)[:250]})
    except Exception:
        pass  # Never replace the primary authorization exception.


def record_denials(action:str):
    from functools import wraps
    def decorator(fn):
        @wraps(fn)
        def wrapped(uid,*args,**kwargs):
            try:
                return fn(uid,*args,**kwargs)
            except PermissionError as exc:
                record_denial(uid,action,args[0] if args else 0,exc)
                raise
        return wrapped
    return decorator


@record_denials("PROPOSE")
def propose(uid: int, disruption_id: int, order_id: int, kind: str, option_index: int = 0) -> int:
    with tx() as c:
        actor(c,uid,("Operations Analyst","Supply Chain Manager","Administrator"))
        order=one(c,"SELECT status FROM orders WHERE id=?",(order_id,))
        must(order is not None,"Order not found")
        must(order["status"] not in ("RECOVERY_IN_PROGRESS","FULFILLED","CANCELLED"),
             "Recovery is already in progress or the order is closed; do not propose a second dispatch")
        active=one(c,"""SELECT id FROM plans WHERE order_id=?
            AND state IN ('PENDING_MANAGER_APPROVAL','CHANGES_REQUESTED','APPROVED')""",(order_id,))
        if active:
            raise ValueError(f"Order already has open recovery proposal #{active['id']}; review it instead")
        options=[r for r in recovery_options(c,disruption_id,order_id) if r["kind"]==kind]
        must(0<=option_index<len(options),"Recovery option no longer available")
        op=options[option_index]
        cur=c.execute("""INSERT INTO plans(disruption_id,order_id,kind,qty,source_warehouse_id,supplier_id,estimate_cost,
            eta_days,rationale,state,proposed_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (disruption_id,order_id,kind,op["qty"],op["source_warehouse_id"],op["supplier_id"],
             op["estimate_cost"],op["eta_days"],op["rationale"]+" "+op["sla_note"],"PENDING_MANAGER_APPROVAL",uid,now()))
        c.execute("UPDATE orders SET status='PENDING_MANAGER_APPROVAL' WHERE id=?",(order_id,))
        audit(c,uid,"PROPOSE","plan",cur.lastrowid,{"kind":kind,"order_id":order_id,"locked":True})
        notify(c,(APPROVERS[kind],),f"Approval required: plan #{cur.lastrowid}, {kind} for order #{order_id}")
        return cur.lastrowid


@record_denials("APPROVAL")
def approve_or_reject(uid: int, plan_id: int, action: str, note: str = "", new_qty: int | None = None) -> str:
    action=action.upper()
    must(action in ("APPROVE","REJECT","MODIFY"),"Unknown decision")
    with tx() as c:
        p=one(c,"SELECT * FROM plans WHERE id=?",(plan_id,))
        must(p is not None,"Plan not found")
        actor(c,uid,(APPROVERS[p["kind"]],))  # admin not an implicit exception
        if uid==p["proposed_by"]:
            raise PermissionError("SEPARATION OF DUTIES: Proposer cannot approve, reject, or modify own plan")
        must(p["state"]=="PENDING_MANAGER_APPROVAL","Plan is not pending approval")
        if action=="MODIFY":
            qty=positive_int(new_qty,"modified qty")
            o=one(c,"SELECT qty FROM orders WHERE id=?",(p["order_id"],))
            must(qty<=o["qty"],"Modified quantity exceeds order quantity")
            must(bool(note.strip()),"Explain the modification")
            newstate="CHANGES_REQUESTED"
            c.execute("UPDATE plans SET qty=?,note=?,state=?,decided_by=?,decided_at=?,version=version+1 WHERE id=?",
               (qty,note[:500],newstate,uid,now(),plan_id))
        else:
            newstate="APPROVED" if action=="APPROVE" else "REJECTED"
            c.execute("UPDATE plans SET state=?,note=?,decided_by=?,decided_at=?,version=version+1 WHERE id=?",
               (newstate,note[:500],uid,now(),plan_id))
            if action=="REJECT":
                c.execute("UPDATE orders SET status='OPEN' WHERE id=?",(p["order_id"],))
        audit(c,uid,action,"plan",plan_id,{"state":newstate,"note":note[:500]})
        notify(c,("Operations Analyst",),f"Recovery #{plan_id} moved to {newstate}")
        return newstate


@record_denials("RESUBMIT")
def resubmit(uid: int, plan_id: int) -> None:
    with tx() as c:
        p=one(c,"SELECT * FROM plans WHERE id=?",(plan_id,))
        must(p is not None,"Plan not found")
        actor(c,uid)
        if uid != p["proposed_by"]: raise PermissionError("Only original proposer can resubmit")
        must(p["state"]=="CHANGES_REQUESTED","Plan not awaiting revision")
        c.execute("UPDATE plans SET state='PENDING_MANAGER_APPROVAL',decided_by=NULL,decided_at=NULL,version=version+1 WHERE id=?",(plan_id,))
        audit(c,uid,"RESUBMIT","plan",plan_id,{"qty":p["qty"]})
        notify(c,(APPROVERS[p["kind"]],),f"Revised proposal #{plan_id} ready for approval")


@record_denials("EXECUTION")
def execute_plan(uid: int, plan_id: int, confirmation: bool) -> str:
    must(confirmation is True,"Explicit execution confirmation is required")
    with tx() as c:
        p=one(c,"SELECT * FROM plans WHERE id=?",(plan_id,))
        must(p is not None,"Plan not found")
        actor(c,uid,(APPROVERS[p["kind"]],))
        must(p["state"]=="APPROVED","Only APPROVED plans may execute")
        must(p["decided_by"] is not None and p["decided_by"]!=p["proposed_by"],"Plan has no independent approval")
        o=one(c,"SELECT * FROM orders WHERE id=?",(p["order_id"],))
        must(o["status"] not in ("FULFILLED","CANCELLED"),"Order already closed")
        # Legacy databases may contain multiple APPROVED plans for the same order.
        # Only one of them may ever mutate inventory, shipment ETA or supplier POs.
        existing=one(c,"""SELECT id FROM plans WHERE order_id=? AND id<>?
            AND state='EXECUTED' ORDER BY id DESC LIMIT 1""",(p["order_id"],plan_id))
        if existing:
            raise ValueError(
                f"Recovery plan #{existing['id']} already executed for {o['order_no']}. "
                "This approved plan is redundant; cancel it instead of executing twice.")
        must(o["status"]!="RECOVERY_IN_PROGRESS",
             "Order recovery is already in progress; duplicate dispatch blocked")
        if p["kind"]=="REALLOCATE":
            stock=one(c,"SELECT * FROM inventory WHERE warehouse_id=? AND sku=?",(p["source_warehouse_id"],o["sku"]))
            must(stock and stock["on_hand"]-stock["reserved"]-stock["safety_stock"]>=p["qty"],"Stock changed: insufficient source inventory")
            c.execute("UPDATE inventory SET on_hand=on_hand-? WHERE id=?",(p["qty"],stock["id"]))
            c.execute("""INSERT INTO inventory(warehouse_id,sku,on_hand,reserved,safety_stock) VALUES (?,?,?,0,0)
              ON CONFLICT(warehouse_id,sku) DO UPDATE SET on_hand=on_hand+excluded.on_hand""",
              (o["warehouse_id"],o["sku"],p["qty"]))
            # A transfer increases target stock but does not claim that goods reached the customer.
        elif p["kind"]=="EXPEDITE":
            sh=one(c,"""SELECT sh.* FROM shipments sh JOIN purchase_orders po ON sh.po_id=po.id
              WHERE po.sku=? AND po.warehouse_id=? AND sh.status IN ('IN_TRANSIT','DELAYED') ORDER BY sh.eta LIMIT 1""",
              (o["sku"],o["warehouse_id"]))
            must(sh is not None,"No eligible shipment remains for expedition")
            revised=max(datetime.now(timezone.utc)+timedelta(days=1),as_dt(sh["eta"])-timedelta(days=3))
            must(revised<as_dt(sh["eta"]),"Shipment ETA cannot be expedited further")
            c.execute("UPDATE shipments SET eta=?,updated_at=? WHERE id=?",(revised.isoformat(),now(),sh["id"]))
        elif p["kind"]=="REORDER":
            supplier=one(c,"""SELECT s.id,s.lead_days,s.delay_days FROM suppliers s JOIN supplier_skus ss ON ss.supplier_id=s.id
              WHERE s.id=? AND ss.sku=? AND s.status='ACTIVE'""",(p["supplier_id"],o["sku"]))
            must(supplier is not None,"Supplier no longer eligible")
            reserved_capacity=c.execute("""UPDATE supplier_sku_capacity SET committed_units=committed_units+?
                 WHERE supplier_id=? AND sku=? AND capacity_units-committed_units>=?""",
                 (p['qty'],p['supplier_id'],o['sku'],p['qty']))
            must(reserved_capacity.rowcount==1,"Supplier capacity exhausted since approval")
            rand=secrets.token_hex(4).upper()
            cur=c.execute("INSERT INTO purchase_orders(po_no,supplier_id,sku,qty,warehouse_id,due_at) VALUES (?,?,?,?,?,?)",
                  (f"PO-REC-{rand}",p["supplier_id"],o["sku"],p["qty"],o["warehouse_id"],days_from_today(supplier["lead_days"]+supplier["delay_days"])))
            c.execute("INSERT INTO shipments(tracking,carrier,vessel,po_id,eta,updated_at,status) VALUES (?,?,?,?,?,?,?)",
                (f"SHP-REC-{rand}","Recovery Freight","Alternate lane",cur.lastrowid,
                 days_from_today(supplier["lead_days"]+supplier["delay_days"]),now(),"IN_TRANSIT"))
        elif p["kind"]=="SPLIT":
            local=one(c,"SELECT * FROM inventory WHERE warehouse_id=? AND sku=?",(o["warehouse_id"],o["sku"]))
            remote=one(c,"SELECT * FROM inventory WHERE warehouse_id=? AND sku=?",(p["source_warehouse_id"],o["sku"]))
            local_free=max(0,local["on_hand"]-local["reserved"]-local["safety_stock"]) if local else 0
            remote_free=max(0,remote["on_hand"]-remote["reserved"]-remote["safety_stock"]) if remote else 0
            qty=min(p["qty"],o["qty"])
            qty_local=min(qty-1,local_free)
            qty_remote=qty-qty_local
            must(qty_local>0 and qty_remote>0 and remote_free>=qty_remote,"Stock changed: split no longer feasible")
            for wh,units in ((o["warehouse_id"],qty_local),(p["source_warehouse_id"],qty_remote)):
                updated=c.execute("UPDATE inventory SET reserved=reserved+? WHERE warehouse_id=? AND sku=? AND on_hand-reserved-safety_stock>=?",
                                  (units,wh,o["sku"],units))
                must(updated.rowcount==1,"Inventory reservation failed")
                c.execute("INSERT INTO fulfillment_tasks(plan_id,order_id,warehouse_id,qty,created_at) VALUES (?,?,?,?,?)",
                          (plan_id,o["id"],wh,units,now()))
        else:
            raise ValueError("Unknown recovery type")
        c.execute("UPDATE plans SET state='EXECUTED',executed_at=?,version=version+1 WHERE id=?",(now(),plan_id))
        c.execute("UPDATE orders SET status='RECOVERY_IN_PROGRESS' WHERE id=?",(o["id"],))
        recompute_all_active_impacts(c)
        audit(c,uid,"EXECUTE_SIMULATED","plan",plan_id,{"kind":p["kind"],"qty":p["qty"],"confirmed":True})
        notify(c,("Operations Analyst","Warehouse Operator","Supply Chain Manager"),f"Recovery #{plan_id} dispatched; fulfillment still needs verification")
        return "EXECUTED"


@record_denials("EXECUTION_CANCELLATION")
def cancel_redundant_plan(uid: int, plan_id: int) -> str:
    """Cancel an obsolete approved plan without touching the already-executed recovery.

    Historic approvals and executed plans remain in the audit trail.
    Backend RBAC and proposer separation are enforced independently of the UI.
    """
    with tx() as c:
        p=one(c,"SELECT * FROM plans WHERE id=?",(plan_id,))
        must(p is not None,"Plan not found")
        actor(c,uid,(APPROVERS[p["kind"]],))
        if uid==p["proposed_by"]:
            raise PermissionError("SEPARATION OF DUTIES: Proposer cannot cancel their own approved plan")
        must(p["state"]=="APPROVED","Only an approved redundant plan can be cancelled")
        other=one(c,"""SELECT id FROM plans WHERE order_id=? AND id<>? AND state='EXECUTED'
            ORDER BY id DESC LIMIT 1""",(p["order_id"],plan_id))
        must(other is not None,"Plan is not redundant; an executed recovery must exist first")
        c.execute("UPDATE plans SET state='CANCELLED',version=version+1 WHERE id=?",(plan_id,))
        audit(c,uid,"CANCEL_REDUNDANT","plan",plan_id,
              {"already_executed_plan":other["id"],"reason":"Duplicate recovery safely cancelled"})
        notify(c,("Operations Analyst", "Supply Chain Manager"),
               f"Redundant recovery #{plan_id} cancelled; executed plan #{other['id']} retained")
        return "CANCELLED"


@record_denials("FULFILLMENT")
def fulfill_task(uid: int, task_id: int):
    with tx() as c:
        actor(c,uid,("Warehouse Operator",))
        task=one(c,"SELECT * FROM fulfillment_tasks WHERE id=?",(task_id,))
        must(task is not None and task["status"]=="PENDING","Task not pending")
        o=one(c,"SELECT * FROM orders WHERE id=?",(task["order_id"],))
        changed=c.execute("""UPDATE inventory SET on_hand=on_hand-?,reserved=reserved-?
           WHERE warehouse_id=? AND sku=? AND reserved>=? AND on_hand>=?""",
          (task["qty"],task["qty"],task["warehouse_id"],o["sku"],task["qty"],task["qty"]))
        must(changed.rowcount==1,"Stock no longer consistent with reservation")
        c.execute("UPDATE fulfillment_tasks SET status='FULFILLED',completed_at=? WHERE id=?",(now(),task_id))
        outstanding=one(c,"SELECT count(*) AS n FROM fulfillment_tasks WHERE plan_id=? AND status='PENDING'",(task["plan_id"],))["n"]
        # Only mark fulfillment complete if dispatched tasks covered the complete order.
        shipped=one(c,"SELECT COALESCE(sum(qty),0) AS qty FROM fulfillment_tasks WHERE plan_id=? AND status='FULFILLED'",(task["plan_id"],))["qty"]
        if outstanding==0 and shipped>=o["qty"]:
            c.execute("UPDATE orders SET status='FULFILLED' WHERE id=?",(o["id"],))
        recompute_all_active_impacts(c)
        audit(c,uid,"FULFILL","task",task_id,{"units":task["qty"],"order":o["order_no"]})
        notify(c,("Operations Analyst","Supply Chain Manager"),f"Warehouse confirmed {task['qty']} units for {o['order_no']}")


IMPORT_RULES={
  "suppliers": ("name","reliability","lead_days"),
  "warehouses": ("code","name","region"),
  "supplier_skus": ("supplier_id","sku"),
  "inventory": ("warehouse_id","sku","on_hand","reserved","safety_stock"),
  "purchase_orders": ("po_no","supplier_id","sku","qty","warehouse_id","due_at"),
  "shipments": ("tracking","carrier","vessel","po_id","eta","updated_at"),
  "orders": ("order_no","customer","sku","qty","warehouse_id","priority","sla_due","value"),
}


def validate_import_record(entity: str, row: dict) -> dict:
    must(entity in IMPORT_RULES,"Unsupported entity; expected one of: "+", ".join(IMPORT_RULES))
    cols=IMPORT_RULES[entity]
    must(isinstance(row,dict) and set(row)==set(cols),f"{entity}: fields must be exactly {', '.join(cols)}")
    clean={k:str(row[k]).strip() if row[k] is not None else "" for k in cols}
    must(all(clean.values()),"Missing or blank value")
    if entity=="suppliers":
        clean["reliability"]=nonnegative_int(clean["reliability"],"reliability")
        must(clean["reliability"]<=100,"Reliability out of range")
        clean["lead_days"]=positive_int(clean["lead_days"],"lead_days")
    if entity in ("supplier_skus","inventory","purchase_orders","shipments","orders"):
        for fld in ("supplier_id","warehouse_id","po_id","qty","on_hand","reserved","safety_stock"):
            if fld in clean:
                clean[fld]=nonnegative_int(clean[fld],fld) if fld in ("on_hand","reserved","safety_stock") else positive_int(clean[fld],fld)
    if entity=="inventory":
        must(clean["reserved"]<=clean["on_hand"],"Reserved quantity exceeds stock")
    if entity=="orders":
        must(clean["priority"] in ("STANDARD","HIGH","CRITICAL"),"Invalid order priority")
        try:clean["value"]=float(clean["value"])
        except ValueError:raise ValueError("Order value must be numeric")
        must(0<=clean["value"]<1e12 and clean["value"]==clean["value"],"Invalid order value")
        ensure_iso(clean["sla_due"])
    if entity=="shipments":
        ensure_iso(clean["eta"]);ensure_iso(clean["updated_at"])
    if entity=="purchase_orders":
        ensure_iso(clean["due_at"])
    for k,v in clean.items():
        if isinstance(v,str):must(len(v)<=180,"Field too long: "+k)
    return clean


def import_data(uid: int, filename: str, raw: bytes) -> dict:
    with read_db() as c:
        actor(c,uid,("Operations Analyst","Administrator"))
    must(len(raw)<=MAX_IMPORT_BYTES,"File exceeds 2MB limit")
    name=Path(filename).name.lower()
    must(name.endswith((".json",".csv")),"Only CSV and JSON supported")
    try: content=raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:raise ValueError("Only UTF-8 files supported") from e
    if name.endswith(".json"):
        try: package=json.loads(content)
        except json.JSONDecodeError as e:raise ValueError("Invalid JSON") from e
        must(isinstance(package,dict),"JSON must be {entity, records}")
        entity=package.get("entity"); records=package.get("records")
    else:
        entity=name.rsplit(".",1)[0]
        reader=csv.DictReader(io.StringIO(content))
        records=list(reader)
    must(isinstance(records,list) and 0<len(records)<=500,"Provide 1–500 records")
    clean=[validate_import_record(entity,r) for r in records]
    columns=IMPORT_RULES[entity]
    statement=f"INSERT INTO {entity}({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
    with tx() as c:
        actor(c,uid,("Operations Analyst","Administrator"))
        try:
            for r in clean:
                c.execute(statement,tuple(r[k] for k in columns))
        except sqlite3.IntegrityError as e:
            raise ValueError(f"Import rejected atomically (duplicate key, FK mismatch or constraint): {e}") from e
        audit(c,uid,"IMPORT",entity,len(clean),{"file":name,"count":len(clean)})
        notify(c,("Operations Analyst","Supply Chain Manager"),f"Imported {len(clean)} {entity} records")
    return {"entity":entity,"count":len(clean)}


def list_data(uid: int) -> dict:
    with read_db() as c:
        user=actor(c,uid)
        summary=one(c,"""SELECT (SELECT count(*) FROM disruptions WHERE status='ACTIVE') AS disruptions,
          (SELECT count(DISTINCT i.order_id) FROM impacts i
               JOIN disruptions d ON d.id=i.disruption_id WHERE d.status='ACTIVE') AS affected,
          (SELECT count(*) FROM plans WHERE state='PENDING_MANAGER_APPROVAL') AS pending,
          (SELECT count(*) FROM plans WHERE state='EXECUTED') AS executing,
          (SELECT count(*) FROM orders WHERE status='FULFILLED') AS fulfilled""")
        disruptions=rows(c,"""SELECT d.*, (SELECT count(*) FROM impacts i WHERE i.disruption_id=d.id) AS impacted,
          (SELECT COALESCE(max(score),0) FROM impacts i WHERE i.disruption_id=d.id) AS max_risk
          FROM disruptions d WHERE d.status='ACTIVE' ORDER BY d.id DESC LIMIT 30""")
        orders=rows(c,"""SELECT o.*, w.code AS warehouse, COALESCE(max(i.score),0) AS risk,
           COALESCE(max(i.short_units),0) AS short_units,
           COALESCE((SELECT group_concat(d.title,' • ') FROM impacts ip JOIN disruptions d ON d.id=ip.disruption_id WHERE ip.order_id=o.id AND d.status='ACTIVE'),'') AS why,
           COALESCE((SELECT explanation FROM impacts ip JOIN disruptions d ON d.id=ip.disruption_id
            WHERE ip.order_id=o.id AND d.status='ACTIVE' ORDER BY score DESC LIMIT 1),'') AS explanation,
           COALESCE((SELECT disruption_id FROM impacts ip JOIN disruptions d ON d.id=ip.disruption_id
            WHERE ip.order_id=o.id AND d.status='ACTIVE' ORDER BY score DESC LIMIT 1),0) AS disruption_id
          FROM orders o JOIN warehouses w ON w.id=o.warehouse_id LEFT JOIN impacts i
            ON i.order_id=o.id AND EXISTS (SELECT 1 FROM disruptions d
                WHERE d.id=i.disruption_id AND d.status='ACTIVE')
          GROUP BY o.id ORDER BY risk DESC, o.value DESC LIMIT 100""")
        plans=rows(c,"""SELECT p.*,COALESCE(p.optimization_run_id,0) AS portfolio_id,
           o.order_no,o.status AS order_status,u.display_name AS proposed_name,du.display_name AS decided_name
          FROM plans p JOIN orders o ON o.id=p.order_id JOIN users u ON u.id=p.proposed_by
          LEFT JOIN users du ON du.id=p.decided_by ORDER BY p.id DESC LIMIT 80""")
        # Display policy is derived server-side from the authenticated database user.
        # This is for UI visibility only; the transaction functions below always
        # recheck permissions, separation of duties and the plan state.
        for plan in plans:
            required_role = APPROVERS.get(plan["kind"], "")
            independent_approver = user["role"] == required_role and uid != plan["proposed_by"]
            plan["approver_role"] = required_role
            plan["can_decide"] = independent_approver and plan["state"] == "PENDING_MANAGER_APPROVAL"
            plan["can_resubmit"] = uid == plan["proposed_by"] and plan["state"] == "CHANGES_REQUESTED"
            other_execution=one(c,"""SELECT id FROM plans
                WHERE order_id=? AND id<>? AND state='EXECUTED' ORDER BY id DESC LIMIT 1""",
                (plan["order_id"],plan["id"]))
            can_control=(
                user["role"] == required_role
                and uid != plan["proposed_by"]
                and plan["decided_by"] is not None
                and plan["decided_by"] != plan["proposed_by"]
            )
            plan["can_execute"] = (
                can_control
                and plan["state"] == "APPROVED"
                and plan["order_status"] != "RECOVERY_IN_PROGRESS"
                and other_execution is None
            )
            # Existing legacy duplicates should be cancellable, never executed twice.
            plan["can_cancel"] = (
                can_control and plan["state"] == "APPROVED" and other_execution is not None
            )
            # Explain why the decision buttons are present or absent.
            # The UI flags are never a substitute for approve_or_reject() RBAC.
            if plan["state"] == "PENDING_MANAGER_APPROVAL":
                if uid == plan["proposed_by"]:
                    plan["approval_hint"] = (
                        f"Self-approval blocked: you proposed this plan. "
                        f"An independent {required_role} must review."
                    )
                elif user["role"] != required_role:
                    plan["approval_hint"] = (
                        f"Not your approval role: {plan['kind']} requires {required_role}; "
                        f"you are {user['role']}."
                    )
                else:
                    plan["approval_hint"] = (
                        f"Eligible for independent {required_role} approval."
                    )
            elif plan["state"] == "APPROVED":
                if other_execution is not None:
                    plan["approval_hint"] = (
                        f"Execution blocked: plan #{other_execution['id']} already dispatched recovery "
                        f"for {plan['order_no']}. Cancel this redundant approved plan; "
                        "inventory and shipment ETA must not change twice."
                    )
                elif plan["order_status"] == "RECOVERY_IN_PROGRESS":
                    plan["approval_hint"] = "Execution blocked: this order already has recovery in progress."
                else:
                    plan["approval_hint"] = (
                        f"Already approved by {plan['decided_name'] or 'an authorized reviewer'}; "
                        "approval cannot be repeated. Execution requires separate confirmation."
                    )
            elif plan["state"] == "CHANGES_REQUESTED":
                plan["approval_hint"] = (
                    "Changes requested. The original proposer must resubmit before approval."
                )
            elif plan["state"] == "REJECTED":
                plan["approval_hint"] = "Rejected. A new valid proposal is required."
            elif plan["state"] == "EXECUTED":
                plan["approval_hint"] = "Already executed in simulation. Review the audit trail."
            elif plan["state"] == "CANCELLED":
                plan["approval_hint"] = "Redundant recovery cancelled; original execution and audit preserved."
            else:
                plan["approval_hint"] = f"No approval action is available in state {plan['state']}."
        portfolios=rows(c,"""SELECT r.id,r.profile,r.created_at,u.display_name AS proposer,
          count(p.id) AS total,
          COALESCE(sum(CASE WHEN p.state='EXECUTED' THEN 1 ELSE 0 END),0) AS executed,
          COALESCE(sum(CASE WHEN p.state='APPROVED' THEN 1 ELSE 0 END),0) AS approved,
          COALESCE(sum(CASE WHEN p.state='PENDING_MANAGER_APPROVAL' THEN 1 ELSE 0 END),0) AS pending,
          COALESCE(sum(CASE WHEN p.state='REJECTED' THEN 1 ELSE 0 END),0) AS rejected
          FROM optimization_runs r JOIN users u ON u.id=r.proposed_by
          LEFT JOIN plans p ON p.optimization_run_id=r.id
          GROUP BY r.id ORDER BY r.id DESC LIMIT 10""")
        for portfolio in portfolios:
            if portfolio['rejected']:
                portfolio['status']='NEEDS_REVISION'
            elif portfolio['total'] and portfolio['executed']==portfolio['total']:
                portfolio['status']='EXECUTED'
            elif portfolio['executed']:
                portfolio['status']='PARTIAL_EXECUTION'
            elif portfolio['approved']==portfolio['total'] and portfolio['total']:
                portfolio['status']='AWAITING_EXECUTION'
            else:
                portfolio['status']='UNDER_APPROVAL'
        inventory=rows(c,"SELECT i.*,w.code AS warehouse FROM inventory i JOIN warehouses w ON w.id=i.warehouse_id ORDER BY i.sku,w.code")
        shipments=rows(c,"""SELECT sh.*,po.po_no,po.sku,po.qty,po.warehouse_id,s.name AS supplier,
          w.code AS warehouse FROM shipments sh JOIN purchase_orders po ON po.id=sh.po_id
          JOIN suppliers s ON s.id=po.supplier_id JOIN warehouses w ON w.id=po.warehouse_id ORDER BY sh.id""")
        suppliers=rows(c,"SELECT * FROM suppliers ORDER BY id")
        notifications=rows(c,"SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 20",(uid,))
        audit_rows=rows(c,"""SELECT a.*,COALESCE(u.display_name,'CARRIER / SYSTEM') AS by_name FROM audit a
          LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 100""")
        tasks=rows(c,"""SELECT t.*,o.order_no,w.code AS warehouse FROM fulfillment_tasks t
          JOIN orders o ON o.id=t.order_id JOIN warehouses w ON w.id=t.warehouse_id ORDER BY t.id DESC""")
        return {"user":user,"summary":summary,"disruptions":disruptions,"orders":orders,"plans":plans,
          "inventory":inventory,"shipments":shipments,"suppliers":suppliers,"notifications":notifications,
          "portfolios":portfolios,
          "audit":audit_rows,"tasks":tasks}


def trace(uid: int, disruption_id: int) -> dict:
    with read_db() as c:
        actor(c,uid)
        d=one(c,"SELECT * FROM disruptions WHERE id=?",(disruption_id,))
        must(d is not None,"Disruption not found")
        shipments=rows(c,"""SELECT sh.tracking,sh.vessel,po.po_no,s.name AS supplier,w.code AS warehouse,po.sku,po.qty,sh.eta,
              COALESCE(i.on_hand,0) AS on_hand,COALESCE(i.reserved,0) AS reserved,
              COALESCE(i.safety_stock,0) AS safety_stock
            FROM shipments sh JOIN purchase_orders po ON po.id=sh.po_id JOIN suppliers s ON s.id=po.supplier_id
            JOIN warehouses w ON w.id=po.warehouse_id
            LEFT JOIN inventory i ON i.warehouse_id=po.warehouse_id AND i.sku=po.sku
            WHERE (sh.id=?) OR (? IS NOT NULL AND po.supplier_id=?) OR (? IS NOT NULL AND po.warehouse_id=? AND po.sku=?) LIMIT 12""",
            (d["shipment_id"],d["supplier_id"],d["supplier_id"],d["warehouse_id"],d["warehouse_id"],d["sku"]))
        for ship in shipments:
            ship["stock_label"]=f"{ship['warehouse']}  {ship['on_hand']} on hand / {ship['reserved']} reserved / {ship['safety_stock']} safety"
        impacted=rows(c,"""SELECT o.order_no,o.customer,o.value,o.sla_due,i.score,i.short_units,w.code AS warehouse
             FROM impacts i JOIN orders o ON o.id=i.order_id JOIN warehouses w ON w.id=o.warehouse_id
             WHERE i.disruption_id=? ORDER BY score DESC""",(disruption_id,))
        return {"disruption":d,"shipments":shipments,"orders":impacted,
                "exposure":sum(x["value"] for x in impacted)}


def mark_notification_read(uid: int, notification_id: int):
    with tx() as c:
        actor(c,uid)
        c.execute("UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?",(notification_id,uid))


def scenario_carrier(uid:int) -> dict:
    with read_db() as c:
        actor(c,uid,("Operations Analyst","Supply Chain Manager","Administrator"))
        sh=one(c,"SELECT * FROM shipments WHERE tracking='SHP-1001'")
        must(sh is not None,"Seed shipment not found")
        active=one(c,"""SELECT id FROM disruptions WHERE kind='CARRIER_DELAY'
            AND shipment_id=? AND status='ACTIVE' ORDER BY id LIMIT 1""",(sh["id"],))
        if active:
            return {"outcome":"NO_CHANGE","disruption_id":active["id"],
                    "affected":one(c,"SELECT count(*) n FROM impacts WHERE disruption_id=?",
                                   (active["id"],))["n"]}
        rev=sh["carrier_revision"]+1
    # Stable demonstration ETA: anchored to the original PO commitment, not
    # the seconds when the button is clicked. Genuine carrier webhooks can
    # still provide hour/minute precision.
    with read_db() as c:
        po=one(c,"SELECT due_at FROM purchase_orders WHERE id=?",(sh["po_id"],))
    eta=(as_dt(po["due_at"])+timedelta(days=5)).isoformat()
    return ingest_carrier({"event_id":f"DEMO-OCEAN-{rev}","tracking":"SHP-1001","revision":rev,
          "eta":eta,"occurred_at":now()},"demo-carrier")


def scenario_supplier(uid:int) -> dict:
    return simulate_supplier_delay(uid,2,8)


def scenario_stock(uid:int) -> dict:
    # The scenario button is a replayable DEMO, not a new physical stock
    # adjustment every click. A genuine new count uses simulate_stock_shortage.
    with read_db() as c:
        actor(c,uid,("Operations Analyst","Warehouse Operator","Administrator"))
        active=one(c,"""SELECT id FROM disruptions WHERE kind='STOCK_SHORTAGE'
            AND warehouse_id=1 AND sku='VALVE-K' AND status='ACTIVE' ORDER BY id LIMIT 1""")
        if active:
            return {"outcome":"NO_CHANGE","disruption_id":active["id"],
                    "affected":one(c,"SELECT count(*) n FROM impacts WHERE disruption_id=?",
                                   (active["id"],))["n"]}
    return simulate_stock_shortage(uid,1,"VALVE-K",45)


def recovery_options_for_user(uid:int,disruption_id:int,order_id:int) -> list[dict]:
    with read_db() as con:
        actor(con,uid)
        return recovery_options(con,disruption_id,order_id)

def authorize_simulation(uid:int):
    with read_db() as con:
        actor(con,uid,("Operations Analyst","Supply Chain Manager","Administrator"))


# --- v1.9 conflict-aware binary portfolio optimization ----------------------
# Optimization is deterministic and never executes anything during simulation.
def preview_optimization(uid: int, profile: str = 'BALANCED', budget: int = 30000,
                         transfer_limit: int = 120) -> dict:
    from .optimizer import optimize, PROFILES
    with read_db() as con:
        actor(con, uid)
        selected=optimize(__import__(__name__, fromlist=['x']), con, profile, budget, transfer_limit)
        comparisons=[]
        for name in PROFILES:
            alternative=(selected if name==profile else
                 optimize(__import__(__name__, fromlist=['x']), con, name, budget, transfer_limit))
            comparisons.append({'profile':name, 'orders':alternative['recovered_orders'],
                'sla_met':alternative['sla_met'], 'cost':alternative['cost'],
                'saved':alternative['saved'], 'net':alternative['net']})
        selected['comparisons']=comparisons
        return selected


@record_denials('OPTIMIZATION_PROPOSAL')
def propose_optimization(uid: int, profile: str, budget: int,
                         transfer_limit: int, signature: str) -> dict:
    """Atomic proposal of the exact validated portfolio preview.

    Independent approvers still authorize individual recovery plans by role.
    No inventory/ETA/PO side effect occurs until those plans are confirmed.
    """
    from .optimizer import optimize
    with tx() as con:
        actor(con,uid,('Operations Analyst','Administrator'))
        result=optimize(__import__(__name__, fromlist=['x']),con,profile,budget,transfer_limit)
        must(result['signature']==signature, 'Inventory/order conditions changed. Refresh What-If before proposing.')
        must(result['picks'], 'No feasible portfolio actions under the selected constraints')
        # Portfolio is based on the same validated recovery choices as the
        # existing one-plan workflow. Every option remains independently reviewed.
        for pick in result['picks']:
            order=one(con,'SELECT * FROM orders WHERE id=?',(pick['order_id'],))
            must(order is not None and order['status']=='OPEN',f"Order {pick['order_no']} is no longer open")
            pending=one(con,"""SELECT id FROM plans WHERE order_id=? AND
                state IN ('PENDING_MANAGER_APPROVAL','CHANGES_REQUESTED','APPROVED')""",(pick['order_id'],))
            must(not pending,f"Order {pick['order_no']} already has a pending recovery")
            candidates=[o for o in recovery_options(con,pick['disruption_id'],pick['order_id'])
                        if o['kind']==pick['kind']]
            idx=pick['kind_index']
            must(0<=idx<len(candidates) and candidates[idx]['qty']==pick['qty']
                 and round(candidates[idx]['estimate_cost'],2)==pick['cost'],
                 'Recovery options changed; refresh the optimization')
        cur=con.execute("""INSERT INTO optimization_runs
           (created_at,proposed_by,profile,budget,transport_limit,signature,scenario_json)
           VALUES (?,?,?,?,?,?,?)""",
           (now(),uid,profile,budget,transfer_limit,signature,json.dumps(result,sort_keys=True)))
        run_id=cur.lastrowid
        ids=[]
        for pick in result['picks']:
            choice=[o for o in recovery_options(con,pick['disruption_id'],pick['order_id'])
                    if o['kind']==pick['kind']][pick['kind_index']]
            cur=con.execute("""INSERT INTO plans
             (disruption_id,order_id,kind,qty,source_warehouse_id,supplier_id,
              estimate_cost,eta_days,rationale,state,proposed_by,created_at,optimization_run_id)
              VALUES (?,?,?,?,?,?,?,?,?,'PENDING_MANAGER_APPROVAL',?,?,?)""",
              (pick['disruption_id'],pick['order_id'],pick['kind'],choice['qty'],
               choice['source_warehouse_id'],choice['supplier_id'],choice['estimate_cost'],
               choice['eta_days'],choice['rationale']+' '+choice['sla_note'],uid,now(),run_id))
            ids.append(cur.lastrowid)
            con.execute("UPDATE orders SET status='PENDING_MANAGER_APPROVAL' WHERE id=?",(pick['order_id'],))
            notify(con,(APPROVERS[pick['kind']],),
                f"Optimization #{run_id}: approve plan #{cur.lastrowid} for {pick['order_no']}")
        audit(con,uid,'OPTIMIZATION_PROPOSE','optimization_run',run_id,
              {'profile':profile,'plan_ids':ids,'budget':budget,
               'transport_limit':transfer_limit,'net_modelled':result['net'],
               'disclaimer':'Modelled avoidance is not contractual penalty savings'})
        return {'run_id':run_id,'plans':ids,'count':len(ids)}
