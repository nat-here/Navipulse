"""Deterministic, exact 0/1 mixed-integer portfolio optimizer (pure Python).

Each binary decision selects one validated recovery option for one customer order.
The resource-sharing inequalities are enforced globally rather than per order.
This is a small bounded exact branch-and-bound solver for the hackathon data;
it has a hard size limit, NOT a general-purpose industrial MILP solver.

No AI/LLM participates in optimization, deadlines, quantities or permissions.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

MAX_ORDERS = 12
MAX_CHOICES_PER_ORDER = 9
MAX_SEARCH_NODES = 1_000_000
PROFILES = {"BALANCED": 1.0, "SLA_FIRST": 2.0, "COST_FIRST": 0.15}


@dataclass(frozen=True)
class Choice:
    order_id: int
    disruption_id: int
    order_no: str
    sku: str
    priority: str
    kind: str
    option_index: int
    title: str
    qty: int
    source_warehouse_id: int | None
    supplier_id: int | None
    cost: int  # cents, no floating-point budget arithmetic
    benefit: int  # cents, scenario-weighted modeled avoided SLA loss
    raw_avoided: int  # cents, unweighted modeled avoided loss
    sla: bool
    eta_days: int
    resources: tuple[tuple[str, int], ...]
    transfer_units: int
    rationale: str

    @property
    def gain(self) -> int:
        return self.benefit - self.cost


def cents(value: float) -> int:
    return round(float(value) * 100)


def available_resources(engine, con) -> dict[str, int]:
    """Stock excludes safety and reservations; pending plans are soft holds.

    Supplier capacity is explicitly synthetic and persisted in supplier_sku_capacity.
    """
    resources: dict[str, int] = {}
    for inv in engine.rows(con, "SELECT warehouse_id,sku,on_hand,reserved,safety_stock FROM inventory"):
        resources[f"W:{inv['warehouse_id']}:{inv['sku']}"] = max(
            0, inv['on_hand'] - inv['reserved'] - inv['safety_stock'])
    for cap in engine.rows(con, "SELECT supplier_id,sku,capacity_units,committed_units FROM supplier_sku_capacity"):
        resources[f"S:{cap['supplier_id']}:{cap['sku']}"] = max(0, cap['capacity_units'] - cap['committed_units'])
    # Pending/approved plans make conservative provisional holds, preventing
    # newly proposed portfolios from double-claiming resources.
    pending = engine.rows(con, """SELECT p.*,o.sku,o.warehouse_id FROM plans p
         JOIN orders o ON o.id=p.order_id
         WHERE p.state IN ('PENDING_MANAGER_APPROVAL','CHANGES_REQUESTED','APPROVED')""")
    for p in pending:
        for key, qty in plan_resource_usage(engine, con, p).items():
            resources[key] = max(0, resources.get(key, 0) - qty)
    return resources


def plan_resource_usage(engine, con, plan: dict) -> dict[str, int]:
    kind, qty, sku = plan['kind'], int(plan['qty']), plan['sku']
    if kind == 'REALLOCATE':
        return {f"W:{plan['source_warehouse_id']}:{sku}": qty}
    if kind == 'REORDER':
        return {f"S:{plan['supplier_id']}:{sku}": qty}
    if kind == 'SPLIT':
        local = engine.one(con, "SELECT * FROM inventory WHERE warehouse_id=? AND sku=?",
                           (plan['warehouse_id'], sku))
        local_free = max(0, local['on_hand']-local['reserved']-local['safety_stock']) if local else 0
        local_qty = min(qty-1, local_free)
        return {f"W:{plan['warehouse_id']}:{sku}": max(0, local_qty),
                f"W:{plan['source_warehouse_id']}:{sku}": qty-max(0, local_qty)}
    return {}


def build_choices(engine, con, profile: str, budget: int, transfer_limit: int):
    if profile not in PROFILES:
        raise ValueError("Invalid optimization profile")
    if not isinstance(budget, int) or budget < 0 or budget > 10_000_000:
        raise ValueError("Budget must be between 0 and 10,000,000")
    if not isinstance(transfer_limit, int) or transfer_limit < 0 or transfer_limit > 100_000:
        raise ValueError("Transfer limit must be between 0 and 100,000 units")
    resources = available_resources(engine, con)
    impacted = engine.rows(con, """SELECT o.*, MAX(i.score) risk, MAX(i.short_units) short_units,
         MIN(i.disruption_id) disruption_id
         FROM orders o JOIN impacts i ON i.order_id=o.id
         JOIN disruptions d ON d.id=i.disruption_id AND d.status='ACTIVE'
         WHERE o.status='OPEN'
         AND NOT EXISTS (SELECT 1 FROM plans p WHERE p.order_id=o.id AND
                         p.state IN ('PENDING_MANAGER_APPROVAL','CHANGES_REQUESTED','APPROVED'))
         GROUP BY o.id ORDER BY risk DESC,o.value DESC LIMIT ?""", (MAX_ORDERS + 1,))
    if len(impacted) > MAX_ORDERS:
        raise ValueError(f"Optimizer supports up to {MAX_ORDERS} exposed orders per run; filter the dataset first")
    choice_groups: list[list[Choice]] = []
    conflicts: list[dict[str, Any]] = []
    for order in impacted:
        gap = int(order['short_units'])
        if gap <= 0:
            continue
        # This is a clearly labeled proxy, not an actual contractual SLA penalty.
        raw = round(cents(order['value']) * 0.18 * (int(order['risk'])/100.0))
        # A partial/late dispatch has no claim to SLA compliance, but is still
        # worth some salvage value (30% of the modeled avoidance).
        group: list[Choice] = []
        candidates = engine.recovery_options(con, order['disruption_id'], order['id'])
        kind_indexes: dict[str, int] = {}
        for op in candidates:
            kind = op['kind']
            idx = kind_indexes.get(kind, 0)
            kind_indexes[kind] = idx + 1
            if int(op['qty']) < gap:
                continue
            source = op.get('source_warehouse_id')
            supplier = op.get('supplier_id')
            usage: dict[str, int] = {}
            transfers = 0
            if kind == 'REALLOCATE':
                usage[f"W:{source}:{order['sku']}"] = int(op['qty'])
                transfers = int(op['qty'])
            elif kind == 'SPLIT':
                # Match the pre-execution split algorithm, conservatively
                # bounding local units by currently unreserved stock.
                local_key = f"W:{order['warehouse_id']}:{order['sku']}"
                local_units = min(int(op['qty'])-1, resources.get(local_key, 0))
                remote_units = int(op['qty']) - local_units
                if local_units <= 0 or remote_units <= 0:
                    continue
                usage[local_key] = local_units
                usage[f"W:{source}:{order['sku']}"] = remote_units
                transfers = remote_units
            elif kind == 'REORDER':
                usage[f"S:{supplier}:{order['sku']}"] = int(op['qty'])
            elif kind == 'EXPEDITE':
                sh = engine.one(con, """SELECT sh.id FROM shipments sh JOIN purchase_orders po ON po.id=sh.po_id
                    WHERE po.sku=? AND po.warehouse_id=? AND sh.status IN ('IN_TRANSIT','DELAYED')
                    ORDER BY sh.eta LIMIT 1""", (order['sku'], order['warehouse_id']))
                if not sh:
                    continue
                # A physical shipment may only be expedited ONCE in this portfolio.
                usage[f"E:{sh['id']}"] = 1
                resources.setdefault(f"E:{sh['id']}", 1)
            else:
                continue
            if any(qty > resources.get(key, 0) for key, qty in usage.items()):
                continue
            sla = bool(op['meets_sla'])
            priority_boost = ({'CRITICAL': 1.4, 'HIGH': 1.0, 'STANDARD': .8}[order['priority']]
                              if profile == 'SLA_FIRST' else 1.0)
            benefit = round(raw * (1.0 if sla else .3) * PROFILES[profile] * priority_boost)
            choice = Choice(order_id=order['id'], disruption_id=order['disruption_id'],
                order_no=order['order_no'], sku=order['sku'], priority=order['priority'],
                kind=kind, option_index=idx, title=op['title'], qty=int(op['qty']),
                source_warehouse_id=source, supplier_id=supplier, cost=cents(op['estimate_cost']),
                benefit=benefit, raw_avoided=round(raw * (1.0 if sla else .3)),
                sla=sla, eta_days=int(op['eta_days']),
                resources=tuple(sorted(usage.items())), transfer_units=transfers,
                rationale=op['rationale'])
            if choice.gain > 0:
                group.append(choice)
        group.sort(key=lambda x: (-x.gain, x.cost, x.kind))
        choice_groups.append(group[:MAX_CHOICES_PER_ORDER])
        if sum(c.qty for c in group if c.kind in ('REALLOCATE','SPLIT')) > 0:
            conflicts.append({"sku": order['sku'], "order_no": order['order_no'], "gap": gap})
    return choice_groups, resources, impacted, conflicts


def solve_exact(groups: list[list[Choice]], capacities: dict[str, int], budget_cents: int, transfer_limit: int):
    """Exact branch-and-bound for a bounded binary multiple-choice MILP.

    z[o,p] is 0/1; Σ_p z[o,p]≤1; Σ usages[r]*z≤cap[r];
    Σ cost*z≤budget; Σ transfers*z≤transfer_limit.
    Maximize Σ (modeled avoided loss - cost)*z.
    """
    groups = sorted(groups, key=lambda g: max((c.gain for c in g), default=0), reverse=True)
    optimistic = [0]*(len(groups)+1)
    for i in range(len(groups)-1, -1, -1):
        optimistic[i] = optimistic[i+1] + max((c.gain for c in groups[i]), default=0)
    best_gain = 0
    best: tuple[Choice,...] = ()
    consumed: dict[str,int] = {}
    chosen: list[Choice] = []
    nodes = 0

    def visit(i: int, gain: int, spent: int, transferred: int):
        nonlocal best_gain, best, nodes
        nodes += 1
        if nodes > MAX_SEARCH_NODES:
            raise ValueError("Portfolio search exceeded its safe computation limit; reduce the affected order set")
        if gain + optimistic[i] <= best_gain:
            return
        if i == len(groups):
            if gain > best_gain:
                best_gain, best = gain, tuple(chosen)
            return
        for option in groups[i]:
            if spent + option.cost > budget_cents or transferred + option.transfer_units > transfer_limit:
                continue
            if any(consumed.get(key,0) + qty > capacities.get(key,0) for key, qty in option.resources):
                continue
            for key,qty in option.resources:
                consumed[key] = consumed.get(key,0) + qty
            chosen.append(option)
            visit(i+1, gain + option.gain, spent + option.cost, transferred + option.transfer_units)
            chosen.pop()
            for key,qty in option.resources:
                consumed[key] -= qty
        visit(i+1, gain, spent, transferred)

    visit(0, 0, 0, 0)
    return sorted(best, key=lambda c: c.order_no), nodes


def optimize(engine, con, profile='BALANCED', budget=30000, transfer_limit=120) -> dict:
    groups, capacities, affected, _ = build_choices(engine, con, profile, budget, transfer_limit)
    choices, nodes = solve_exact(groups, capacities, cents(budget), transfer_limit)
    selected_orders = {x.order_id for x in choices}
    # Identify contested source capacity, not just repeated order names.
    competitors: dict[str,set[str]] = {}
    for group in groups:
        for choice in group:
            for key,qty in choice.resources:
                if key.startswith('W:') and qty:
                    competitors.setdefault(key,set()).add(choice.order_no)
    conflicts = [{"resource": key.replace('W:', 'WH ').replace(':',' / '),
                  "contenders": ', '.join(sorted(orders)),
                  "capacity": capacities[key]}
                 for key,orders in sorted(competitors.items()) if len(orders)>1]
    picks = [{"order_id": c.order_id,"disruption_id":c.disruption_id,
              "order_no":c.order_no,"sku":c.sku,"kind":c.kind,"kind_index":c.option_index,
              "source":(f"Warehouse #{c.source_warehouse_id}" if c.source_warehouse_id else
                        f"Supplier #{c.supplier_id}" if c.supplier_id else "Inbound freight"),
              "qty":c.qty,"cost":round(c.cost/100,2),"avoided_loss":round(c.raw_avoided/100,2),
              "sla_note":"Within SLA" if c.sla else "Late recovery / salvage",
              "rationale":c.rationale,"title":c.title} for c in choices]
    signature = hashlib.sha256(json.dumps(
       {"profile":profile,"budget":budget,"transfer_limit":transfer_limit,
        "choices":[{"order_id":p['order_id'],"disruption_id":p['disruption_id'],
                    "kind":p['kind'],"idx":p['kind_index'],"qty":p['qty'],
                    "cost":p['cost']} for p in picks]}, sort_keys=True).encode()).hexdigest()
    return {"profile":profile, "budget":budget,"transfer_limit":transfer_limit,
            "picks":picks,"signature":signature, "examined":len(affected),
            "recovered_orders":len(selected_orders),"uncovered_orders":len(affected)-len(selected_orders),
            "saved":round(sum(c.raw_avoided for c in choices)/100,2),
            "cost":round(sum(c.cost for c in choices)/100,2),
            "net":round((sum(c.raw_avoided-c.cost for c in choices))/100,2),
            "transferred":sum(c.transfer_units for c in choices),
            "sla_met":sum(c.sla for c in choices),"conflicts":conflicts,"nodes":nodes}
