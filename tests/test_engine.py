"""Unittest suite: no external packages needed to test domain rules."""
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta

from disruption_iq import engine as e


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.original=e.DB_PATH
        e.DB_PATH=Path(self.temp.name)/"test.db"
        e.init_db()
        self.analyst=e.login("analyst","Analyst#2026")["id"]
        self.manager=e.login("manager","Manager#2026")["id"]
        self.proc=e.login("procurement","Procure#2026")["id"]
        self.warehouse=e.login("warehouse","Warehouse#2026")["id"]
        self.admin=e.login("admin","Admin#2026")["id"]

    def tearDown(self):
        e.DB_PATH=self.original
        self.temp.cleanup()

    def carrier_payload(self, id="evt-1",revision=1,eta_days=8):
        return {"event_id":id,"tracking":"SHP-1001","revision":revision,
                "eta":e.days_from_today(eta_days),"occurred_at":e.now()}

    def test_login_and_roles(self):
        with self.assertRaises(PermissionError):e.login("analyst","wrong")
        with self.assertRaises(PermissionError):e.scenario_carrier(self.warehouse)
        with self.assertRaises(PermissionError):e.simulate_supplier_delay(self.warehouse,2,5)
        with self.assertRaises(PermissionError):e.import_data(self.warehouse,"orders.csv",b"abc")

    def test_two_disruptions_and_lineage(self):
        first=e.scenario_carrier(self.analyst)
        second=e.scenario_supplier(self.analyst)
        self.assertEqual(first["affected"],2)
        self.assertGreaterEqual(second["affected"],2)
        trace=e.trace(self.analyst,first["disruption_id"])
        self.assertEqual(trace["shipments"][0]["po_no"],"PO-8401")
        self.assertEqual(trace["shipments"][0]["warehouse"],"BLR-01")
        self.assertIn("ORD-90241",[o["order_no"] for o in trace["orders"]])
        self.assertEqual(trace["exposure"],378000.0)
        self.assertEqual(e.list_data(self.analyst)["summary"]["disruptions"],2)

    def test_duplicate_stale_and_conflicting_event(self):
        payload=self.carrier_payload()
        result=e.ingest_carrier(payload)
        self.assertEqual(result["outcome"],"APPLIED")
        self.assertEqual(e.ingest_carrier(payload)["outcome"],"DUPLICATE")
        self.assertEqual(e.list_data(self.analyst)["summary"]["disruptions"],1)
        conflicting={**payload,"eta":e.days_from_today(10)}
        with self.assertRaises(ValueError):e.ingest_carrier(conflicting)
        stale=self.carrier_payload("evt-stale",1,12)
        self.assertEqual(e.ingest_carrier(stale)["outcome"],"STALE_IGNORED")
        with e.read_db() as c:
            sh=e.one(c,"SELECT carrier_revision FROM shipments WHERE id=1")
            self.assertEqual(sh["carrier_revision"],1)

    def test_invalid_webhook_rolls_back(self):
        with self.assertRaises(ValueError):e.ingest_carrier(self.carrier_payload(eta_days=1)|{"tracking":"NOPE"})
        with self.assertRaises(ValueError):e.ingest_carrier(self.carrier_payload()|{"revision":-1})
        with self.assertRaises(ValueError):e.ingest_carrier(self.carrier_payload()|{"eta":"2027-foo"})
        with e.read_db() as c:
            self.assertEqual(e.one(c,"SELECT count(*) AS n FROM disruptions")["n"],0)

    def test_independent_manager_gate(self):
        e.scenario_carrier(self.analyst)
        pid=e.propose(self.analyst,1,1,"REALLOCATE")
        with e.read_db() as c:
            self.assertEqual(e.one(c,"SELECT status FROM orders WHERE id=1")["status"],"PENDING_MANAGER_APPROVAL")
        with self.assertRaises(PermissionError):e.approve_or_reject(self.analyst,pid,"APPROVE")
        with self.assertRaises(PermissionError):e.approve_or_reject(self.proc,pid,"APPROVE")
        with self.assertRaises(ValueError):e.execute_plan(self.manager,pid,True)
        self.assertEqual(e.approve_or_reject(self.manager,pid,"APPROVE"),"APPROVED")
        with self.assertRaises(ValueError):e.execute_plan(self.manager,pid,False)
        self.assertEqual(e.execute_plan(self.manager,pid,True),"EXECUTED")
        with self.assertRaises(ValueError):e.execute_plan(self.manager,pid,True)
        self.assertEqual(e.list_data(self.manager)["summary"]["executing"],1)

    def test_manager_cannot_self_approve(self):
        e.scenario_carrier(self.manager)
        pid=e.propose(self.manager,1,1,"REALLOCATE")
        with self.assertRaisesRegex(PermissionError,"SEPARATION OF DUTIES"):
            e.approve_or_reject(self.manager,pid,"APPROVE")
        with e.read_db() as c:
            self.assertEqual(e.one(c,"SELECT state FROM plans WHERE id=?",(pid,))["state"],"PENDING_MANAGER_APPROVAL")

    def test_change_request_resubmit_and_reject(self):
        e.scenario_carrier(self.analyst)
        pid=e.propose(self.analyst,1,1,"REALLOCATE")
        self.assertEqual(e.approve_or_reject(self.manager,pid,"MODIFY","Reduce to controlled lot",20),"CHANGES_REQUESTED")
        with self.assertRaises(ValueError):e.approve_or_reject(self.manager,pid,"APPROVE")
        with self.assertRaises(PermissionError):e.resubmit(self.manager,pid)
        e.resubmit(self.analyst,pid)
        self.assertEqual(e.approve_or_reject(self.manager,pid,"REJECT","Cost too high"),"REJECTED")
        with e.read_db() as c:
            self.assertEqual(e.one(c,"SELECT status FROM orders WHERE id=1")["status"],"OPEN")

    def test_procurement_approves_supplier(self):
        e.scenario_carrier(self.analyst)
        pid=e.propose(self.analyst,1,1,"REORDER")
        with self.assertRaises(PermissionError):e.approve_or_reject(self.manager,pid,"APPROVE")
        e.approve_or_reject(self.proc,pid,"APPROVE")
        e.execute_plan(self.proc,pid,True)
        with e.read_db() as c:
            self.assertEqual(e.one(c,"SELECT count(*) AS n FROM purchase_orders WHERE po_no LIKE 'PO-REC-%'")["n"],1)

    def test_inventory_check_repeat_execution(self):
        e.scenario_carrier(self.analyst)
        pid=e.propose(self.analyst,1,1,"REALLOCATE")
        e.approve_or_reject(self.manager,pid,"APPROVE")
        with e.tx() as c:
            c.execute("UPDATE inventory SET on_hand=reserved+safety_stock WHERE sku='SENSOR-X' AND warehouse_id=2")
        with self.assertRaises(ValueError):e.execute_plan(self.manager,pid,True)
        with e.read_db() as c:
            self.assertEqual(e.one(c,"SELECT state FROM plans WHERE id=?",(pid,))["state"],"APPROVED")

    def test_split_reserves_then_warehouse_fulfills(self):
        e.scenario_carrier(self.analyst)
        pid=e.propose(self.analyst,1,1,"SPLIT")
        e.approve_or_reject(self.manager,pid,"APPROVE")
        e.execute_plan(self.manager,pid,True)
        with e.read_db() as c:
            tasks=e.rows(c,"SELECT * FROM fulfillment_tasks ORDER BY id")
            self.assertEqual(sum(t["qty"] for t in tasks),58)
        for task in tasks:
            with self.assertRaises(PermissionError):e.fulfill_task(self.analyst,task["id"])
            e.fulfill_task(self.warehouse,task["id"])
        with e.read_db() as c:
            self.assertEqual(e.one(c,"SELECT status FROM orders WHERE id=1")["status"],"FULFILLED")

    def test_csv_json_import_atomicity(self):
        data=b"code,name,region\nHYD-04,Hyderabad Hub,South\nCBE-05,Coimbatore Hub,South\n"
        self.assertEqual(e.import_data(self.analyst,"warehouses.csv",data)["count"],2)
        bad=b"code,name,region\nABC-05,Other Hub,West\nHYD-04,Duplicate Hub,South\n"
        with self.assertRaises(ValueError):e.import_data(self.analyst,"warehouses.csv",bad)
        with e.read_db() as c:
            self.assertIsNone(e.one(c,"SELECT * FROM warehouses WHERE code='ABC-05'"))
        obj={"entity":"supplier_skus","records":[{"supplier_id":4,"sku":"SENSOR-X"}]}
        self.assertEqual(e.import_data(self.analyst,"new.json",json.dumps(obj).encode())["count"],1)
        with self.assertRaises(ValueError):e.import_data(self.analyst,"bad.json",b"{}")

    def test_stock_shortage_enforces_reserved(self):
        with self.assertRaises(ValueError):e.simulate_stock_shortage(self.warehouse,1,"VALVE-K",130)
        result=e.simulate_stock_shortage(self.warehouse,1,"VALVE-K",45)
        self.assertGreaterEqual(result["affected"],1)
        self.assertTrue(any(x["action"]=="STOCK_SHORTAGE" for x in e.list_data(self.admin)["audit"]))


if __name__=="__main__":unittest.main()
