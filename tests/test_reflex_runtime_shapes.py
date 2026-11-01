"""DB -> Reflex state contract tests, including runtime-selected detail panels.

These tests require no Reflex runtime. They validate real synthetic SQL records,
not just Python source annotations, so raw DB rows cannot silently violate a
TypedDict state contract.
"""
from __future__ import annotations

import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import get_type_hints
import unittest

from disruption_iq import engine, schemas


ROOT = Path(__file__).resolve().parents[1]


def assert_record_matches(test: unittest.TestCase, record: dict, schema: type):
    required = schema.__required_keys__
    test.assertTrue(required <= record.keys(), f"{schema.__name__}: missing {required - record.keys()}")
    for field, expected in get_type_hints(schema).items():
        if field not in record:
            continue
        value = record[field]
        if expected is float:
            test.assertIsInstance(value, (int, float), f"{schema.__name__}.{field}")
        else:
            test.assertIsInstance(value, expected, f"{schema.__name__}.{field}")


class RuntimeViewModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.previous = engine.DB_PATH
        engine.DB_PATH = Path(self.temp.name) / 'test.db'
        engine.init_db()
        self.analyst = engine.login('analyst', 'Analyst#2026')['id']
        self.manager = engine.login('manager', 'Manager#2026')['id']

    def tearDown(self):
        engine.DB_PATH = self.previous
        self.temp.cleanup()

    def test_raw_trace_converts_to_small_typed_detail(self):
        for scenario in (engine.scenario_carrier, engine.scenario_supplier, engine.scenario_stock):
            disruption_id = scenario(self.analyst)['disruption_id']
            with self.subTest(disruption_id=disruption_id):
                result = engine.trace(self.analyst, disruption_id)
                raw = result['disruption']
                self.assertNotIn('kind_label', raw)
                detail = schemas.to_disruption_detail(raw)
                self.assertEqual(set(detail), {'title', 'detail'})
                self.assertEqual(detail['title'], raw['title'])
                assert_record_matches(self, detail, schemas.DisruptionDetailRow)
                for item in result['shipments']:
                    assert_record_matches(self, item, schemas.LineageShipmentRow)
                for item in result['orders']:
                    assert_record_matches(self, item, schemas.LineageOrderRow)

    def test_invalid_trace_detail_is_rejected(self):
        for value in ({}, {'title': 'X'}, {'title': 'X', 'detail': None}):
            with self.subTest(record=value):
                with self.assertRaises(ValueError):
                    schemas.to_disruption_detail(value)

    def test_all_dashboard_rows_come_from_actual_engine_data(self):
        engine.scenario_carrier(self.analyst)
        engine.scenario_supplier(self.analyst)
        engine.scenario_stock(self.analyst)
        data = engine.list_data(self.analyst)
        collections = {
            'disruptions': schemas.DisruptionRow,
            'orders': schemas.OrderRow,
            'plans': schemas.PlanRow,
            'inventory': schemas.InventoryRow,
            'shipments': schemas.ShipmentRow,
            'suppliers': schemas.SupplierRow,
            'notifications': schemas.NotificationRow,
            'audit': schemas.AuditRow,
            'tasks': schemas.FulfillmentTaskRow,
        }
        for row in data['disruptions']:
            row['kind_label'] = row['kind'].replace('_', ' / ')
        for row in data['orders']:
            row['sla_short'] = row['sla_due'][:10]
            row['value_label'] = f"{row['value']:,.0f}"
        for row in data['audit']:
            row['date_short'] = row['created_at'][:19]
        for key, schema in collections.items():
            for row in data[key]:
                with self.subTest(collection=key, row_id=row['id']):
                    assert_record_matches(self, row, schema)
        for row in data['orders']:
            if row['disruption_id']:
                assert_record_matches(self, row, schemas.OrderRow)
                options = engine.recovery_options_for_user(self.analyst, row['disruption_id'], row['id'])
                for option in options:
                    option['kind_index'] = 0
                    assert_record_matches(self, option, schemas.RecoveryOptionRow)

    def test_approved_plan_and_warehouse_tasks_fit_types(self):
        carrier = engine.scenario_carrier(self.analyst)
        pid = engine.propose(self.analyst, carrier['disruption_id'], 1, 'SPLIT')
        plan = engine.list_data(self.analyst)['plans'][0]
        assert_record_matches(self, plan, schemas.PlanRow)
        engine.approve_or_reject(self.manager, pid, 'APPROVE')
        engine.execute_plan(self.manager, pid, confirmation=True)
        tasks = engine.list_data(self.manager)['tasks']
        self.assertGreater(len(tasks), 0)
        for task in tasks:
            assert_record_matches(self, task, schemas.FulfillmentTaskRow)

    def test_state_uses_detail_projection_instead_of_raw_sql_row(self):
        source = ast.parse((ROOT / 'disruption_iq' / 'state.py').read_text(encoding='utf8'))
        cls = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == 'State')
        annotations = {
            node.target.id: ast.unparse(node.annotation)
            for node in cls.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        self.assertEqual(annotations['selected_disruption_info'], 'DisruptionDetailRow')
        handler = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'inspect_disruption')
        assignments = [node for node in ast.walk(handler) if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Attribute) and target.attr == 'selected_disruption_info'
            for target in node.targets
        )]
        self.assertEqual(len(assignments), 1)
        self.assertEqual(ast.unparse(assignments[0].value), 'to_disruption_detail(result[\'disruption\'])')


if __name__ == '__main__':
    unittest.main()
