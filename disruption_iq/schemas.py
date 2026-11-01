"""Typed Reflex-facing view models.

The SQLite engine deliberately returns dictionaries.  These TypedDict types
preserve that wire format while making per-column types available to Reflex's
compile-time Var / foreach validation.  Do not use dict[str, Any] for a list
rendered by rx.foreach: it makes item["key"] an untyped Reflex Var.
"""
from typing import Mapping, TypedDict


class DisruptionDetailRow(TypedDict):
    """Fields rendered by the selected-disruption detail panel only."""
    title: str
    detail: str


def to_disruption_detail(record: Mapping[str, object]) -> DisruptionDetailRow:
    """Project the raw SQL disruption record to the Reflex detail-panel contract.

    engine.trace() returns a SQL disruption row, while the dashboard's
    DisruptionRow has additional derived keys (kind_label, impacted, max_risk).
    Do not assign a raw trace row to a DisruptionRow state var.
    """
    title = record.get("title")
    detail = record.get("detail")
    if not isinstance(title, str) or not isinstance(detail, str):
        raise ValueError("Invalid disruption detail: title and detail must be text")
    return {"title": title, "detail": detail}


class DisruptionRow(TypedDict):
    id: int
    kind: str
    kind_label: str
    title: str
    detail: str
    impacted: int
    max_risk: int


class OrderRow(TypedDict):
    id: int
    order_no: str
    customer: str
    sku: str
    warehouse: str
    priority: str
    qty: int
    value: float
    value_label: str
    sla_due: str
    sla_short: str
    risk: int
    explanation: str
    disruption_id: int


class PlanRow(TypedDict):
    id: int
    kind: str
    state: str
    order_no: str
    rationale: str
    proposed_name: str
    qty: int
    approver_role: str
    approval_hint: str
    can_decide: bool
    can_resubmit: bool
    can_execute: bool
    can_cancel: bool
    portfolio_id: int


class InventoryRow(TypedDict):
    id: int
    warehouse: str
    sku: str
    on_hand: int
    reserved: int


class ShipmentRow(TypedDict):
    id: int
    tracking: str
    vessel: str
    warehouse: str
    status: str


class SupplierRow(TypedDict):
    id: int
    name: str
    reliability: int
    delay_days: int


class NotificationRow(TypedDict):
    id: int
    message: str
    is_read: int


class AuditRow(TypedDict):
    id: int
    action: str
    entity_type: str
    entity_id: str
    by_name: str
    created_at: str
    date_short: str


class FulfillmentTaskRow(TypedDict):
    id: int
    order_no: str
    warehouse: str
    qty: int
    status: str


class RiskBarRow(TypedDict):
    label: str
    risk: int


class LineageShipmentRow(TypedDict):
    tracking: str
    vessel: str
    po_no: str
    supplier: str
    stock_label: str
    sku: str


class LineageOrderRow(TypedDict):
    order_no: str
    customer: str
    warehouse: str
    short_units: int
    score: int


class RecoveryOptionRow(TypedDict):
    kind: str
    kind_index: int
    title: str
    estimate_cost: float
    rationale: str
    sla_note: str
    meets_sla: bool
    qty: int
    eta_days: int

class OptimizationScenarioRow(TypedDict):
    profile: str
    orders: int
    sla_met: int
    cost: float
    saved: float
    net: float


class OptimizationPickRow(TypedDict):
    order_id: int
    disruption_id: int
    order_no: str
    sku: str
    kind: str
    kind_index: int
    source: str
    qty: int
    cost: float
    avoided_loss: float
    sla_note: str
    rationale: str
    title: str


class OptimizationConflictRow(TypedDict):
    resource: str
    contenders: str
    capacity: int


class OptimizationHistoryRow(TypedDict):
    id: int
    profile: str
    created_at: str
    proposer: str
    total: int
    executed: int
    approved: int
    pending: int
    rejected: int
    status: str
