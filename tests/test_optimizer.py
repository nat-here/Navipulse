"""Real portfolio optimization and submission regression tests (stdlib only)."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from disruption_iq import engine as e, optimizer

class OptimizerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.prior=e.DB_PATH
        e.DB_PATH=Path(self.tmp.name)/'optimization.sqlite3'
        e.init_db()
        self.analyst=e.login('analyst','Analyst#2026')['id']
        self.manager=e.login('manager','Manager#2026')['id']
        self.procurement=e.login('procurement','Procure#2026')['id']
        self.warehouse=e.login('warehouse','Warehouse#2026')['id']
        for scenario in (e.scenario_carrier,e.scenario_supplier,e.scenario_stock):
            scenario(self.analyst)

    def tearDown(self):
        e.DB_PATH=self.prior
        self.tmp.cleanup()

    def test_solver_respects_capacity_and_budget_and_selects_highest_benefit(self):
        def option(order,gain,qty):
            return optimizer.Choice(order,1,f'ORDER-{order}','SENSOR-X','HIGH','REALLOCATE',0,
                    'Reallocate',qty,2,None,cost=100,benefit=100+gain,raw_avoided=500,
                    sla=True,eta_days=1,resources=(('W:2:SENSOR-X',qty),),
                    transfer_units=qty,rationale='test')
        groups=[[option(1,800,40)],[option(2,400,30)]]
        picks,nodes=optimizer.solve_exact(groups,{'W:2:SENSOR-X':50},budget_cents=200,transfer_limit=50)
        self.assertEqual([p.order_id for p in picks],[1])
        picks,_=optimizer.solve_exact(groups,{'W:2:SENSOR-X':80},budget_cents=200,transfer_limit=80)
        self.assertEqual([p.order_id for p in picks],[1,2])
        picks,_=optimizer.solve_exact(groups,{'W:2:SENSOR-X':80},budget_cents=99,transfer_limit=80)
        self.assertFalse(picks)
        self.assertGreater(nodes,0)

    def test_preview_is_read_only_and_conflicts_are_explained(self):
        with e.read_db() as c:
            before=e.one(c,'SELECT count(*) AS n FROM plans')['n']
            stock=e.rows(c,'SELECT warehouse_id,sku,on_hand,reserved FROM inventory')
        result=e.preview_optimization(self.analyst,'BALANCED',30000,120)
        self.assertEqual(len(result['comparisons']),3)
        self.assertGreater(result['recovered_orders'],0)
        self.assertTrue(result['conflicts'])
        self.assertEqual(result['recovered_orders'],len({p['order_id'] for p in result['picks']}))
        self.assertLessEqual(result['cost'],30000)
        self.assertLessEqual(result['transferred'],120)
        self.assertLessEqual(result['recovered_orders'],result['examined'])
        with e.read_db() as c:
            self.assertEqual(e.one(c,'SELECT count(*) AS n FROM plans')['n'],before)
            self.assertEqual(e.rows(c,'SELECT warehouse_id,sku,on_hand,reserved FROM inventory'),stock)

    def test_recovery_proposals_audited_and_independently_approved(self):
        result=e.preview_optimization(self.analyst,'BALANCED',30000,120)
        proposed=e.propose_optimization(self.analyst,'BALANCED',30000,120,result['signature'])
        self.assertEqual(proposed['count'],len(result['picks']))
        with e.read_db() as c:
            self.assertEqual(e.one(c,'SELECT count(*) AS n FROM optimization_runs')['n'],1)
            self.assertEqual(e.one(c,"SELECT count(*) AS n FROM audit WHERE action='OPTIMIZATION_PROPOSE'")['n'],1)
            plans=e.rows(c,'SELECT * FROM plans WHERE optimization_run_id=?',(proposed['run_id'],))
            self.assertTrue(all(p['state']=='PENDING_MANAGER_APPROVAL' for p in plans))
        self.assertTrue(any(p['kind']=='REALLOCATE' for p in plans))
        for plan in plans:
            approving=self.procurement if plan['kind']=='REORDER' else self.manager
            with self.assertRaises(PermissionError):
                e.approve_or_reject(self.analyst,plan['id'],'APPROVE')
            wrong=self.manager if plan['kind']=='REORDER' else self.procurement
            with self.assertRaises(PermissionError):
                e.approve_or_reject(wrong,plan['id'],'APPROVE')
            self.assertEqual(e.approve_or_reject(approving,plan['id'],'APPROVE'),'APPROVED')
        # Approval does NOT change the warehouse stock or execute automatically.
        with e.read_db() as c:
            self.assertEqual(e.one(c,'SELECT count(*) AS n FROM plans WHERE state="EXECUTED"')['n'],0)
        with self.assertRaises(ValueError):
            e.propose_optimization(self.analyst,'BALANCED',30000,120,result['signature'])

    def test_full_portfolio_approve_and_execute_separately(self):
        choice=e.preview_optimization(self.analyst,'BALANCED',30000,120)
        submitted=e.propose_optimization(self.analyst,'BALANCED',30000,120,choice['signature'])
        with e.read_db() as con:
            plans=e.rows(con,'SELECT * FROM plans WHERE optimization_run_id=?',(submitted['run_id'],))
            starting_inventory=e.rows(con,'SELECT id,on_hand,reserved FROM inventory')
        # Approval is a distinct event for each eligible role, not dispatch.
        for plan in plans:
            approver=self.procurement if plan['kind']=='REORDER' else self.manager
            e.approve_or_reject(approver,plan['id'],'APPROVE')
        with e.read_db() as con:
            self.assertEqual(starting_inventory,e.rows(con,'SELECT id,on_hand,reserved FROM inventory'))
            self.assertEqual(e.list_data(self.analyst)['portfolios'][0]['status'],'AWAITING_EXECUTION')
        for plan in plans:
            approver=self.procurement if plan['kind']=='REORDER' else self.manager
            with self.assertRaises(ValueError):
                e.execute_plan(approver,plan['id'],False)
            self.assertEqual(e.execute_plan(approver,plan['id'],True),'EXECUTED')
        self.assertEqual(e.list_data(self.analyst)['portfolios'][0]['status'],'EXECUTED')
        with e.read_db() as con:
            self.assertEqual(e.one(con,'SELECT count(*) n FROM audit WHERE action="EXECUTE_SIMULATED"')['n'],len(plans))

    def test_stale_portfolio_is_rejected_atomically(self):
        result=e.preview_optimization(self.analyst,'BALANCED',30000,120)
        with e.tx() as c:
            # Change a source stock value, without changing audit/other records.
            c.execute('UPDATE inventory SET on_hand=on_hand-50 WHERE warehouse_id=2 AND sku="SENSOR-X"')
        with self.assertRaisesRegex(ValueError,'Refresh What-If'):
            e.propose_optimization(self.analyst,'BALANCED',30000,120,result['signature'])
        with e.read_db() as c:
            self.assertEqual(e.one(c,'SELECT count(*) n FROM plans')['n'],0)
            self.assertEqual(e.one(c,'SELECT count(*) n FROM optimization_runs')['n'],0)

    def test_role_and_invalid_scenario_and_parameters(self):
        with self.assertRaises(PermissionError):
            e.propose_optimization(self.warehouse,'BALANCED',30000,120,'invalid')
        for kwargs in ({'profile':'IMPOSSIBLE'}, {'budget':-10}, {'transfer_limit':-4}):
            with self.assertRaises(ValueError):
                e.preview_optimization(self.analyst,**kwargs)

    def test_existing_database_can_initialize_idempotently(self):
        e.init_db()
        e.init_db()
        with e.read_db() as c:
            cols={row['name'] for row in c.execute('PRAGMA table_info(plans)')}
            self.assertIn('optimization_run_id',cols)
            self.assertEqual(e.one(c,'SELECT count(*) AS n FROM supplier_sku_capacity')['n'],6)
            self.assertEqual(e.one(c,'SELECT count(*) AS n FROM users')['n'],5)

    def test_capacity_enforced_during_supplier_execution(self):
        e.propose(self.analyst,1,1,'REORDER')
        with e.read_db() as c:
            p=e.one(c,"SELECT * FROM plans WHERE kind='REORDER'")
            self.assertIsNotNone(p)
        e.approve_or_reject(self.procurement,p['id'],'APPROVE')
        with e.tx() as c:
            c.execute('UPDATE supplier_sku_capacity SET committed_units=80 WHERE supplier_id=? AND sku="SENSOR-X"',(p['supplier_id'],))
        with self.assertRaisesRegex(ValueError,'capacity exhausted'):
            e.execute_plan(self.procurement,p['id'],True)
        with e.read_db() as c:
            self.assertEqual(e.one(c,'SELECT state FROM plans WHERE id=?',(p['id'],))['state'],'APPROVED')
            self.assertEqual(e.one(c,"SELECT count(*) n FROM purchase_orders WHERE po_no LIKE 'PO-REC-%'")['n'],0)

if __name__=='__main__': unittest.main()
