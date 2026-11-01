"""Reflex state controllers. Every mutation delegates to backend RBAC in engine.py."""
from __future__ import annotations

import reflex as rx

from . import engine, ai
from .schemas import (
    AuditRow, DisruptionDetailRow, DisruptionRow, FulfillmentTaskRow, InventoryRow,
    OptimizationScenarioRow, OptimizationPickRow, OptimizationConflictRow, OptimizationHistoryRow,
    LineageOrderRow, LineageShipmentRow, NotificationRow, OrderRow,
    PlanRow, RecoveryOptionRow, RiskBarRow, ShipmentRow, SupplierRow,
    to_disruption_detail,
)


class State(rx.State):
    # Backend-only authenticated identity. Never accept user ID or role from a button argument.
    _uid: int = 0
    username: str = ""
    password: str = ""
    display_name: str = ""
    user_initial: str = ""
    role: str = ""
    authenticated: bool = False
    tab: str = "overview"
    message: str = ""
    ai_mode: str = ""
    loading_ai: bool = False
    ai_brief: str = ""

    # Strongly typed rows ensure foreach keys remain typed Vars at compile time.
    summary: dict[str, int] = {}
    disruptions: list[DisruptionRow] = []
    orders: list[OrderRow] = []
    plans: list[PlanRow] = []
    inventory: list[InventoryRow] = []
    shipments: list[ShipmentRow] = []
    suppliers: list[SupplierRow] = []
    notifications: list[NotificationRow] = []
    audits: list[AuditRow] = []
    tasks: list[FulfillmentTaskRow] = []
    risk_bars: list[RiskBarRow] = []
    optimizer_scenarios: list[OptimizationScenarioRow] = []
    optimizer_picks: list[OptimizationPickRow] = []
    optimizer_conflicts: list[OptimizationConflictRow] = []
    optimizer_history: list[OptimizationHistoryRow] = []
    optimizer_profile: str = 'BALANCED'
    optimizer_budget_text: str = '30000'
    optimizer_transfer_text: str = '120'
    optimizer_signature: str = ''
    optimizer_ready: bool = False
    optimizer_examined: int = 0
    optimizer_recovered: int = 0
    optimizer_sla_met: int = 0
    optimizer_cost: str = '$0'
    optimizer_saved: str = '$0'
    optimizer_net: str = '$0'
    optimizer_notice: str = 'Run an optimization to compare recovery strategies. No resources change during a What-If simulation.'


    selected_disruption: int = 0
    selected_order: int = 0
    selected_disruption_info: DisruptionDetailRow = {"title": "", "detail": ""}
    selected_order_info: OrderRow = {}
    lineage_nodes: list[LineageShipmentRow] = []
    lineage_orders: list[LineageOrderRow] = []
    exposure: str = "$0"
    options: list[RecoveryOptionRow] = []
    modify_qty: str = "1"
    decision_note: str = ""
    executing_plan_id: int = 0
    execution_error: str = ""
    import_status: str = ""
    webhook_json: str = ""
    login_error: str = ""

    # Reflex 0.9+ disables automatic state setters by default.
    # Explicit event handlers are required for all on_change and on_click bindings.
    @rx.event
    def set_message(self, value: str):
        self.message = value

    @rx.event
    def set_username(self, value: str):
        self.username = value

    @rx.event
    def set_password(self, value: str):
        self.password = value

    @rx.event
    def set_decision_note(self, value: str):
        self.decision_note = value

    @rx.event
    def set_modify_qty(self, value: str):
        self.modify_qty = value

    @rx.event
    def set_webhook_json(self, value: str):
        self.webhook_json = value

    @rx.event
    def set_optimizer_profile(self, value: str):
        if value in ('BALANCED', 'SLA_FIRST', 'COST_FIRST'):
            self.optimizer_profile = value
            self.optimizer_ready = False

    @rx.event
    def set_optimizer_budget_text(self, value: str):
        self.optimizer_budget_text = value
        self.optimizer_ready = False

    @rx.event
    def set_optimizer_transfer_text(self, value: str):
        self.optimizer_transfer_text = value
        self.optimizer_ready = False

    @rx.event
    def run_optimizer(self):
        try:
            if not self._uid:
                raise PermissionError('Sign in before running optimization')
            # Each input is validated on the backend, not trusted as a browser value.
            budget = int(self.optimizer_budget_text)
            transfer = int(self.optimizer_transfer_text)
            result = engine.preview_optimization(self._uid, self.optimizer_profile, budget, transfer)
            self.optimizer_scenarios = result['comparisons']
            self.optimizer_picks = result['picks']
            self.optimizer_conflicts = result['conflicts']
            self.optimizer_signature = result['signature']
            self.optimizer_ready = bool(result['picks'])
            self.optimizer_examined = result['examined']
            self.optimizer_recovered = result['recovered_orders']
            self.optimizer_sla_met = result['sla_met']
            self.optimizer_cost = f"${result['cost']:,.0f}"
            self.optimizer_saved = f"${result['saved']:,.0f}"
            self.optimizer_net = f"${result['net']:,.0f}"
            self.optimizer_notice = (
                f"Exact 0/1 optimizer evaluated {result['examined']} exposed orders "
                f"and {result['nodes']} search nodes. No database inventory changed."
            )
        except (ValueError, PermissionError) as exc:
            self.optimizer_ready = False
            self.optimizer_signature = ''
            self.optimizer_notice = f"Optimization unavailable: {exc}"

    @rx.event
    def submit_optimized_portfolio(self):
        try:
            if not self.optimizer_ready or not self.optimizer_signature:
                raise ValueError('Run a fresh What-If scenario before proposing')
            result=engine.propose_optimization(self._uid,self.optimizer_profile,
                int(self.optimizer_budget_text),int(self.optimizer_transfer_text),self.optimizer_signature)
            self.optimizer_ready=False
            self.optimizer_signature=''
            self.optimizer_notice=f"Portfolio #{result['run_id']} submitted; each plan requires an independent role-specific approval."
            self.message=self.optimizer_notice
            self._refresh()
            self.tab='approvals'
        except (ValueError, PermissionError) as exc:
            self.optimizer_ready=False
            self.optimizer_signature=''
            self.optimizer_notice=f"Proposal blocked: {exc}. Rerun What-If to refresh resources."

    @rx.event
    def load(self):
        engine.init_db()
        self.ai_mode=ai.availability()
        if self._uid:
            try:self._refresh()
            except (PermissionError, ValueError):
                self._uid=0
                self.authenticated=False
                self.display_name=""
                self.role=""

    def _refresh(self):
        data=engine.list_data(self._uid)
        self.summary=data["summary"]
        for disruption in data["disruptions"]:
            disruption["kind_label"] = disruption["kind"].replace("_", " / ")
        self.disruptions=data["disruptions"]
        self.orders=data["orders"]
        for order in self.orders:
            order["sla_short"]=order["sla_due"][:10]
            order["value_label"]=f"{order['value']:,.0f}"
        self.plans=data["plans"]
        self.optimizer_history=data["portfolios"]
        self.inventory=data["inventory"]
        self.shipments=data["shipments"]
        self.suppliers=data["suppliers"]
        self.notifications=data["notifications"]
        self.audits=data["audit"]
        for row in self.audits:
            row["date_short"]=row["created_at"][:19]
        self.tasks=data["tasks"]
        self.risk_bars=[{"label":x["order_no"].replace("ORD-",""),"risk":x["risk"]} for x in self.orders if x["risk"]>0][:8]

    @rx.event
    def refresh(self):
        if not self._uid: return
        try:
            self._refresh()
            self.message="Latest records synchronized"
        except (ValueError,PermissionError) as exc: self.message=str(exc)

    @rx.event
    def sign_in(self):
        try:
            user=engine.login(self.username,self.password)
            self._uid=user["id"]
            self.display_name=user["display_name"]
            self.user_initial=user["display_name"][0]
            self.role=user["role"]
            self.authenticated=True
            self.password=""
            self.login_error=""
            self.tab="overview"
            self._refresh()
        except (ValueError,PermissionError) as exc:
            self.login_error=str(exc)

    @rx.event
    def signout(self):
        self.executing_plan_id=0
        self.execution_error=""
        self._uid=0
        self.authenticated=False
        self.username=""
        self.password=""
        self.display_name=""
        self.user_initial=""
        self.role=""
        self.message=""
        self.summary={}
        self.orders=[]
        self.plans=[]
        self.disruptions=[]
        self.tab="overview"
        self.optimizer_ready=False
        self.optimizer_signature=''
        self.optimizer_picks=[]
        self.optimizer_scenarios=[]
        self.optimizer_conflicts=[]
        self.optimizer_history=[]

    @rx.event
    def change_tab(self,tab:str):
        if not self._uid:return
        if tab not in ("overview","disruptions","orders","recovery","optimizer","approvals","network","audit","ingest"):
            return
        self.tab=tab
        self.message=""
        self._refresh()

    @rx.event
    def run_carrier(self):
        try:
            result=engine.scenario_carrier(self._uid)
            self.message=("Carrier delay already tracked — no duplicate alert created"
                          if result.get("outcome") in ("NO_CHANGE", "DUPLICATE") else
                          f"Carrier alert {result.get('outcome','APPLIED').lower()}: {result.get('affected',0)} downstream orders flagged")
            self._refresh();self.tab="disruptions"
        except (ValueError,PermissionError) as exc:self.message=f"Blocked: {exc}"

    @rx.event
    def run_supplier(self):
        try:
            result=engine.scenario_supplier(self._uid)
            self.message=("Supplier delay already tracked — no duplicate alert created"
                          if result.get("outcome") in ("NO_CHANGE", "DUPLICATE") else
                          f"Supplier event {result.get('outcome','APPLIED').lower()}: {result.get('affected',0)} downstream orders flagged")
            self._refresh();self.tab="disruptions"
        except (ValueError,PermissionError) as exc:self.message=f"Blocked: {exc}"

    @rx.event
    def run_stock(self):
        try:
            result=engine.scenario_stock(self._uid)
            self.message=("Stock shortage scenario already active — inventory was not deducted again"
                          if result.get("outcome") in ("NO_CHANGE", "DUPLICATE") else
                          f"Cycle-count shortage {result.get('outcome','APPLIED').lower()}: {result.get('affected',0)} downstream orders flagged")
            self._refresh();self.tab="disruptions"
        except (ValueError,PermissionError) as exc:self.message=f"Blocked: {exc}"

    @rx.event
    def inspect_disruption(self, disruption_id: int):
        try:
            self._refresh()
            result=engine.trace(self._uid,disruption_id)
            self.selected_disruption=disruption_id
            self.selected_disruption_info=to_disruption_detail(result["disruption"])
            self.lineage_nodes=result["shipments"]
            self.lineage_orders=result["orders"]
            self.exposure="${:,.0f}".format(result["exposure"])
            self.tab="disruptions"
        except (ValueError,PermissionError) as exc:self.message=str(exc)

    @rx.event
    def inspect_order(self,order_id:int,disruption_id:int):
        try:
            self._refresh()
            selected=next((x for x in self.orders if x["id"]==order_id),None)
            if not selected or not disruption_id:
                raise ValueError("Select an order linked to an active disruption")
            options=engine.recovery_options_for_user(self._uid,disruption_id,order_id)
            kind_counts={}
            for candidate in options:
                key=candidate["kind"]
                candidate["kind_index"]=kind_counts.get(key,0)
                kind_counts[key]=kind_counts.get(key,0)+1
            self.options=options
            self.selected_order=order_id
            self.selected_disruption=disruption_id
            self.selected_order_info=selected
            self.ai_brief="Select ‘Generate AI brief’ to explain validated recovery candidates."
            self.tab="recovery"
        except (ValueError,PermissionError) as exc:self.message=str(exc)

    @rx.event
    def ask_ai(self):
        try:
            result=engine.trace(self._uid,self.selected_disruption)
            disruption=result["disruption"]
            self.ai_brief,self.ai_mode=ai.summarize_with_status(
                disruption,result,self.selected_order_info,self.options
            )
        except (ValueError,PermissionError) as exc:self.message=str(exc)

    @rx.event
    def propose_option(self,kind:str,option_index:int):
        try:
            pid=engine.propose(self._uid,self.selected_disruption,self.selected_order,kind,option_index)
            self._refresh()
            self.message=f"Proposal #{pid} locked at PENDING_MANAGER_APPROVAL. Independent approval required."
            self.tab="approvals"
        except (ValueError,PermissionError) as exc:self.message=f"Proposal rejected: {exc}"

    @rx.event
    def decide(self, plan_id:int, action:str):
        try:
            qty=int(self.modify_qty) if action=="MODIFY" else None
            state=engine.approve_or_reject(self._uid,plan_id,action,self.decision_note,qty)
            self.message=f"Plan #{plan_id}: {state}. Approval does not trigger execution."
            self.decision_note="";self._refresh()
        except (ValueError,PermissionError) as exc:self.message=f"Decision rejected: {exc}"

    @rx.event
    def resubmit_plan(self,plan_id:int):
        try:
            engine.resubmit(self._uid,plan_id)
            self.message=f"Plan #{plan_id} submitted again for independent approval"
            self._refresh()
        except (ValueError,PermissionError) as exc:self.message=str(exc)

    @rx.event
    def choose_execute(self,plan_id:int):
        # Recheck server-derived eligibility even if a stale browser displays a button.
        self._refresh()
        match=next((p for p in self.plans if p["id"]==plan_id),None)
        if not match or not match["can_execute"]:
            self.executing_plan_id=0
            self.execution_error=""
            self.message=(match["approval_hint"] if match else "Plan not available")
            return
        self.execution_error=""
        self.executing_plan_id=plan_id
        self.message=f"Execution requires explicit confirmation for plan #{plan_id}."

    @rx.event
    def cancel_execute(self):
        self.execution_error=""
        self.executing_plan_id=0
        self.message="Execution cancelled: no operational data changed"

    @rx.event
    def confirm_execute(self):
        try:
            pid=self.executing_plan_id
            must=pid>0
            if not must: raise ValueError("Select an approved plan to execute")
            engine.execute_plan(self._uid,pid,confirmation=True)
            self.executing_plan_id=0
            self.execution_error=""
            self.message=f"Plan #{pid} executed in simulation; audit + stock/order effects persisted."
            self._refresh()
        except (ValueError,PermissionError) as exc:
            self.execution_error=f"Execution blocked: {exc}"
            self.message=self.execution_error
            self._refresh()

    @rx.event
    def cancel_redundant(self,plan_id:int):
        try:
            engine.cancel_redundant_plan(self._uid,plan_id)
            self.executing_plan_id=0
            self.execution_error=""
            self.message=f"Plan #{plan_id} safely cancelled as redundant. Existing execution preserved."
            self._refresh()
        except (ValueError,PermissionError) as exc:
            self.message=f"Cancellation blocked: {exc}"

    @rx.event
    def complete_task(self,task_id:int):
        try:
            engine.fulfill_task(self._uid,task_id)
            self.message=f"Warehouse task #{task_id} fulfilled"
            self._refresh()
        except (ValueError,PermissionError) as exc:self.message=f"Fulfillment denied: {exc}"

    @rx.event
    async def import_files(self,files:list[rx.UploadFile]):
        try:
            if not files: raise ValueError("Choose a CSV or JSON file first")
            if len(files)!=1: raise ValueError("Upload one file at a time")
            raw=await files[0].read()
            result=engine.import_data(self._uid,files[0].name,raw)
            self.import_status=f"Committed {result['count']} {result['entity']} records atomically"
            self.message="Import complete"
            self._refresh()
        except (ValueError,PermissionError) as exc:
            self.import_status=f"Import rejected — {exc}"

    @rx.event
    def mark_read(self,notification_id:int):
        try:
            engine.mark_notification_read(self._uid,notification_id);self._refresh()
        except (ValueError,PermissionError) as exc:self.message=str(exc)

    @rx.event
    def ingest_json(self):
        try:
            import json
            payload=json.loads(self.webhook_json)
            # In-app carrier simulation is available to authorized operations roles.
            engine.authorize_simulation(self._uid)
            result=engine.ingest_carrier(payload,source="console-simulator")
            self.message=f"Simulated carrier event: {result['outcome']}, {result['affected']} impacted orders"
            self._refresh();self.tab="disruptions"
        except (ValueError,PermissionError,TypeError) as exc:self.message=f"Webhook rejected: {exc}"
