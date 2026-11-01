"""Regression tests: a second recovery must never dispatch an order twice."""
import tempfile
import unittest
from pathlib import Path
from disruption_iq import engine as e


class DuplicateExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.before=e.DB_PATH
        e.DB_PATH=Path(self.tmp.name)/'demo.db'
        e.init_db()
        self.analyst=e.login('analyst','Analyst#2026')['id']
        self.manager=e.login('manager','Manager#2026')['id']
        self.procurement=e.login('procurement','Procure#2026')['id']
        self.admin=e.login('admin','Admin#2026')['id']
        e.scenario_supplier(self.analyst)

    def tearDown(self):
        e.DB_PATH=self.before
        self.tmp.cleanup()

    def legacy_second_approved_plan(self, executed_id):
        """Simulate approved duplicates already stored by the v1.7 application."""
        with e.tx() as c:
            old=e.one(c,'SELECT * FROM plans WHERE id=?',(executed_id,))
            cur=c.execute('''INSERT INTO plans(disruption_id,order_id,kind,qty,source_warehouse_id,
                supplier_id,estimate_cost,eta_days,rationale,state,proposed_by,decided_by,created_at,decided_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
                    old['disruption_id'],old['order_id'],old['kind'],old['qty'],old['source_warehouse_id'],
                    old['supplier_id'],old['estimate_cost'],old['eta_days'],old['rationale'],
                    'APPROVED',self.admin,self.manager,e.now(),e.now()))
            return cur.lastrowid

    def test_existing_expedite_is_the_only_execution(self):
        pid=e.propose(self.analyst,1,3,'EXPEDITE')
        e.approve_or_reject(self.manager,pid,'APPROVE')
        self.assertEqual(e.execute_plan(self.manager,pid,True),'EXECUTED')
        with e.read_db() as c:
            shipment_eta=e.one(c,"SELECT eta FROM shipments WHERE tracking='SHP-1002'")['eta']
            original_audit=e.one(c,"SELECT COUNT(*) AS n FROM audit WHERE action='EXECUTE_SIMULATED'")['n']
        redundant=self.legacy_second_approved_plan(pid)
        card=next(x for x in e.list_data(self.manager)['plans'] if x['id']==redundant)
        self.assertFalse(card['can_execute'])
        self.assertTrue(card['can_cancel'])
        self.assertIn('already dispatched',card['approval_hint'])
        with self.assertRaisesRegex(ValueError,'already executed'):
            e.execute_plan(self.manager,redundant,True)
        with e.read_db() as c:
            self.assertEqual(e.one(c,"SELECT eta FROM shipments WHERE tracking='SHP-1002'")['eta'],shipment_eta)
            self.assertEqual(e.one(c,"SELECT COUNT(*) AS n FROM audit WHERE action='EXECUTE_SIMULATED'")['n'],original_audit)
            self.assertEqual(e.one(c,'SELECT state FROM plans WHERE id=?',(redundant,))['state'],'APPROVED')
        self.assertEqual(e.cancel_redundant_plan(self.manager,redundant),'CANCELLED')
        with e.read_db() as c:
            self.assertEqual(e.one(c,'SELECT state FROM plans WHERE id=?',(pid,))['state'],'EXECUTED')
            self.assertEqual(e.one(c,'SELECT state FROM plans WHERE id=?',(redundant,))['state'],'CANCELLED')
            self.assertEqual(e.one(c,"SELECT COUNT(*) AS n FROM audit WHERE action='CANCEL_REDUNDANT'")['n'],1)
            self.assertEqual(e.one(c,"SELECT eta FROM shipments WHERE tracking='SHP-1002'")['eta'],shipment_eta)

    def test_prevent_new_recovery_after_execution(self):
        pid=e.propose(self.analyst,1,3,'EXPEDITE')
        e.approve_or_reject(self.manager,pid,'APPROVE')
        e.execute_plan(self.manager,pid,True)
        with self.assertRaisesRegex(ValueError,'already in progress'):
            e.propose(self.admin,1,3,'EXPEDITE')
        with e.read_db() as c:
            self.assertEqual(e.recovery_options(c,1,3),[])

    def test_only_authorized_independent_approver_can_cancel(self):
        pid=e.propose(self.analyst,1,3,'EXPEDITE')
        e.approve_or_reject(self.manager,pid,'APPROVE')
        e.execute_plan(self.manager,pid,True)
        redundant=self.legacy_second_approved_plan(pid)
        for uid in (self.analyst,self.procurement):
            with self.assertRaises(PermissionError):
                e.cancel_redundant_plan(uid,redundant)
        with self.assertRaises(PermissionError):
            e.cancel_redundant_plan(self.admin,redundant)
        self.assertEqual(e.cancel_redundant_plan(self.manager,redundant),'CANCELLED')
        with self.assertRaises(ValueError):
            e.cancel_redundant_plan(self.manager,redundant)

    def test_execution_without_other_executed_plan_still_works(self):
        pid=e.propose(self.analyst,1,3,'EXPEDITE')
        e.approve_or_reject(self.manager,pid,'APPROVE')
        self.assertTrue(next(x for x in e.list_data(self.manager)['plans'] if x['id']==pid)['can_execute'])
        self.assertEqual(e.execute_plan(self.manager,pid,True),'EXECUTED')

    def test_inline_failure_display_and_cancel_button_present(self):
        from pathlib import Path
        src=Path(__file__).parents[1]/'disruption_iq'
        ui=(src/'disruption_iq.py').read_text(encoding='utf-8')
        state=(src/'state.py').read_text(encoding='utf-8')
        self.assertIn('State.execution_error',ui)
        self.assertIn('CANCEL REDUNDANT PLAN',ui)
        self.assertIn('engine.cancel_redundant_plan',state)
        self.assertIn('self.execution_error=f"Execution blocked:',state)

if __name__ == '__main__':
    unittest.main()
