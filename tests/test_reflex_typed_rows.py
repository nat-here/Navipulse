"""Static regression checks for Reflex 0.10 typed rx.foreach collections.

Runs without installing Reflex, but does not substitute for a live frontend build.
"""
import ast
from pathlib import Path
import unittest

from disruption_iq import schemas

ROOT = Path(__file__).resolve().parents[1]
STATE = ast.parse((ROOT / "disruption_iq" / "state.py").read_text(encoding="utf8"))
UI = ast.parse((ROOT / "disruption_iq" / "disruption_iq.py").read_text(encoding="utf8"))


ROW_TYPES = {
    "disruptions": schemas.DisruptionRow,
    "orders": schemas.OrderRow,
    "plans": schemas.PlanRow,
    "inventory": schemas.InventoryRow,
    "shipments": schemas.ShipmentRow,
    "suppliers": schemas.SupplierRow,
    "notifications": schemas.NotificationRow,
    "audits": schemas.AuditRow,
    "tasks": schemas.FulfillmentTaskRow,
    "risk_bars": schemas.RiskBarRow,
    "lineage_nodes": schemas.LineageShipmentRow,
    "lineage_orders": schemas.LineageOrderRow,
    "options": schemas.RecoveryOptionRow,
    "optimizer_scenarios": schemas.OptimizationScenarioRow,
    "optimizer_picks": schemas.OptimizationPickRow,
    "optimizer_conflicts": schemas.OptimizationConflictRow,
    "optimizer_history": schemas.OptimizationHistoryRow,
}


RENDERERS = {
    "signal_card": schemas.DisruptionRow,
    "order_card": schemas.OrderRow,
    "decision_plan": schemas.PlanRow,
    "network_stock": schemas.InventoryRow,
    "network_shipment": schemas.ShipmentRow,
    "supplier_row": schemas.SupplierRow,
    "notification_row": schemas.NotificationRow,
    "audit_row": schemas.AuditRow,
    "fulfillment_row": schemas.FulfillmentTaskRow,
    "lineage_record": schemas.LineageShipmentRow,
    "impact_order": schemas.LineageOrderRow,
    "recovery_option": schemas.RecoveryOptionRow,
    "optimization_scenario": schemas.OptimizationScenarioRow,
    "optimization_pick": schemas.OptimizationPickRow,
    "optimization_conflict": schemas.OptimizationConflictRow,
    "optimization_history": schemas.OptimizationHistoryRow,
}


class TypedRowContractTests(unittest.TestCase):
    def test_foreach_state_properties_have_typed_rows(self):
        state_cls = next(n for n in STATE.body if isinstance(n, ast.ClassDef) and n.name == "State")
        annotations = {
            target.target.id: target.annotation
            for target in state_cls.body
            if isinstance(target, ast.AnnAssign) and isinstance(target.target, ast.Name)
        }
        for field, model in ROW_TYPES.items():
            with self.subTest(field=field):
                ann = annotations[field]
                self.assertIsInstance(ann, ast.Subscript)
                self.assertEqual(ast.unparse(ann), f"list[{model.__name__}]")
                self.assertNotIn("Any", ast.unparse(ann))

    def test_each_renderer_uses_existing_typed_dict_keys(self):
        functions = {f.name: f for f in UI.body if isinstance(f, ast.FunctionDef)}
        for fn, schema in RENDERERS.items():
            func = functions[fn]
            first_arg = func.args.args[0].arg
            fields = schema.__annotations__
            for node in ast.walk(func):
                if not (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                        and node.value.id == first_arg and isinstance(node.slice, ast.Constant)
                        and isinstance(node.slice.value, str)):
                    continue
                with self.subTest(renderer=fn, key=node.slice.value):
                    self.assertIn(node.slice.value, fields)
                    self.assertNotEqual(str(fields[node.slice.value]), "typing.Any")

    def test_no_untyped_frontend_dictionaries(self):
        state_cls = next(n for n in STATE.body if isinstance(n, ast.ClassDef) and n.name == "State")
        for node in state_cls.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                with self.subTest(field=node.target.id):
                    self.assertNotIn("Any", ast.unparse(node.annotation))


if __name__ == "__main__":
    unittest.main()
