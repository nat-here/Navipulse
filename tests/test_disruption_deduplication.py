"""Regression coverage for duplicate scenario clicks, carrier event revisions and cleanup."""
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from disruption_iq import engine as e
from scripts.consolidate_disruptions import apply_consolidation, find_duplicate_groups


class IncidentEpisodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.previous = e.DB_PATH
        e.DB_PATH = Path(self.tmp.name) / 'test.db'
        e.init_db()
        self.analyst = e.login('analyst', 'Analyst#2026')['id']
        self.manager = e.login('manager', 'Manager#2026')['id']
        self.warehouse = e.login('warehouse', 'Warehouse#2026')['id']

    def tearDown(self):
        e.DB_PATH = self.previous
        self.tmp.cleanup()

    def test_repeated_carrier_scenario_does_not_create_cards_or_events(self):
        first = e.scenario_carrier(self.analyst)
        self.assertEqual(first['outcome'], 'APPLIED')
        for _ in range(8):
            replay = e.scenario_carrier(self.analyst)
            self.assertEqual(replay['outcome'], 'NO_CHANGE')
            self.assertEqual(replay['disruption_id'], first['disruption_id'])
        with e.read_db() as db:
            self.assertEqual(e.one(db, 'SELECT count(*) n FROM disruptions')['n'], 1)
            self.assertEqual(e.one(db, 'SELECT count(*) n FROM carrier_events')['n'], 1)
        self.assertEqual(e.list_data(self.analyst)['summary']['disruptions'], 1)

    def test_different_carrier_event_ids_are_retained_without_duplicate_incidents(self):
        first = e.scenario_carrier(self.analyst)
        with e.read_db() as db:
            sh = e.one(db, "SELECT * FROM shipments WHERE tracking='SHP-1001'")
        # A newer carrier revision containing the same ETA is still persisted.
        unchanged = e.ingest_carrier({
            'event_id': 'CARRIER-REV-2', 'tracking': sh['tracking'],
            'revision': sh['carrier_revision'] + 1, 'eta': sh['eta'],
            'occurred_at': e.now(),
        }, 'mariner-live')
        self.assertEqual(unchanged['outcome'], 'NO_CHANGE')
        later_eta = (e.as_dt(sh['eta']) + timedelta(days=1)).isoformat()
        updated = e.ingest_carrier({
            'event_id': 'CARRIER-REV-3', 'tracking': sh['tracking'],
            'revision': sh['carrier_revision'] + 2, 'eta': later_eta,
            'occurred_at': e.now(),
        }, 'mariner-live')
        self.assertEqual(updated['outcome'], 'UPDATED')
        self.assertEqual(updated['disruption_id'], first['disruption_id'])
        with e.read_db() as db:
            self.assertEqual(e.one(db, 'SELECT count(*) n FROM carrier_events')['n'], 3)
            self.assertEqual(e.one(db, 'SELECT count(*) n FROM disruptions')['n'], 1)
            self.assertIn(later_eta[:10], e.one(db,'SELECT detail FROM disruptions WHERE id=1')['detail'])

    def test_carrier_correction_resolves_and_clears_live_order_risk(self):
        e.scenario_carrier(self.analyst)
        with e.read_db() as db:
            ship = e.one(db, "SELECT * FROM shipments WHERE tracking='SHP-1001'")
            po = e.one(db, 'SELECT due_at FROM purchase_orders WHERE id=?',(ship['po_id'],))
        result = e.ingest_carrier({
            'event_id': 'CARRIER-RECOVERY', 'tracking': ship['tracking'],
            'revision': ship['carrier_revision'] + 1,
            'eta': po['due_at'], 'occurred_at': e.now(),
        }, 'mariner-live')
        self.assertEqual(result['outcome'], 'RESOLVED')
        board = e.list_data(self.analyst)
        self.assertEqual(board['summary']['disruptions'], 0)
        self.assertEqual(board['summary']['affected'], 0)
        self.assertEqual(len(board['disruptions']), 0)
        self.assertTrue(all(o['risk'] == 0 for o in board['orders']))
        with e.read_db() as db:
            self.assertEqual(e.one(db, "SELECT status FROM disruptions WHERE id=1")['status'], 'RESOLVED')
            self.assertEqual(e.one(db, "SELECT count(*) n FROM carrier_events")['n'], 2)

    def test_supplier_click_idempotence_and_updated_delay(self):
        first=e.scenario_supplier(self.analyst)
        for _ in range(5):
            replay=e.scenario_supplier(self.analyst)
            self.assertEqual(replay['outcome'],'NO_CHANGE')
            self.assertEqual(replay['disruption_id'],first['disruption_id'])
        changed=e.simulate_supplier_delay(self.analyst,2,9)
        self.assertEqual(changed['outcome'],'UPDATED')
        self.assertEqual(changed['disruption_id'],first['disruption_id'])
        with e.read_db() as db:
            self.assertEqual(e.one(db,'SELECT count(*) n FROM disruptions')['n'],1)
            self.assertEqual(e.one(db, 'SELECT delay_days FROM suppliers WHERE id=2')['delay_days'],9)

    def test_stock_scenario_replay_does_not_deduct_inventory_twice(self):
        first=e.scenario_stock(self.analyst)
        with e.read_db() as db:
            initial=e.one(db,"SELECT on_hand FROM inventory WHERE warehouse_id=1 AND sku='VALVE-K'")['on_hand']
        for _ in range(5):
            replay=e.scenario_stock(self.analyst)
            self.assertEqual(replay['outcome'],'NO_CHANGE')
            self.assertEqual(replay['disruption_id'],first['disruption_id'])
        with e.read_db() as db:
            self.assertEqual(e.one(db,"SELECT on_hand FROM inventory WHERE warehouse_id=1 AND sku='VALVE-K'")['on_hand'],initial)
            self.assertEqual(e.one(db,'SELECT count(*) n FROM disruptions')['n'],1)
        # A separately confirmed cycle count *is* an additional physical adjustment,
        # but is attached to the existing active incident rather than a new card.
        second=e.simulate_stock_shortage(self.warehouse,1,'VALVE-K',5)
        self.assertEqual(second['outcome'],'UPDATED')
        self.assertEqual(second['disruption_id'],first['disruption_id'])
        with e.read_db() as db:
            self.assertEqual(e.one(db,"SELECT on_hand FROM inventory WHERE warehouse_id=1 AND sku='VALVE-K'")['on_hand'],initial-5)
            self.assertEqual(e.one(db,'SELECT count(*) n FROM disruptions')['n'],1)

    def test_existing_duplicate_cleanup_preserves_plans_events_and_audit(self):
        first=e.scenario_carrier(self.analyst)
        with e.tx() as db:
            original=e.one(db, 'SELECT * FROM disruptions WHERE id=?', (first['disruption_id'],))
            cur=db.execute("""INSERT INTO disruptions(source,event_id,kind,title,shipment_id,detail,severity,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",('demo-carrier','LEGACY-DUP-2','CARRIER_DELAY',
                original['title'],original['shipment_id'],original['detail'],'CRITICAL',e.now()))
            second_id=cur.lastrowid
            e.recompute_all_active_impacts(db)
        pid=e.propose(self.analyst,second_id,1,'REALLOCATE')
        e.approve_or_reject(self.manager,pid,'APPROVE')
        e.execute_plan(self.manager,pid,True)
        with e.read_db() as db:
            self.assertEqual(len(find_duplicate_groups(db)),1)
            before_events=e.one(db,'SELECT count(*) n FROM carrier_events')['n']
            before_audit=e.one(db,'SELECT count(*) n FROM audit')['n']
            before_plans=e.one(db,'SELECT count(*) n FROM plans')['n']
            before_impacts=e.one(db,'SELECT count(*) n FROM impacts')['n']
        with e.tx() as db:
            outcome=apply_consolidation(db)
        self.assertEqual(len(outcome),1)
        self.assertEqual(outcome[0]['kept'],second_id)  # executed plan wins
        self.assertEqual(outcome[0]['superseded'],[first['disruption_id']])
        board=e.list_data(self.analyst)
        self.assertEqual(board['summary']['disruptions'],1)
        self.assertEqual(len(board['disruptions']),1)
        with e.read_db() as db:
            self.assertEqual(e.one(db,'SELECT count(*) n FROM carrier_events')['n'],before_events)
            self.assertEqual(e.one(db,'SELECT count(*) n FROM plans')['n'],before_plans)
            self.assertEqual(e.one(db,'SELECT count(*) n FROM impacts')['n'],before_impacts)
            self.assertGreater(e.one(db,'SELECT count(*) n FROM audit')['n'],before_audit)
            self.assertEqual(e.one(db,'SELECT disruption_id FROM plans WHERE id=?',(pid,))['disruption_id'],second_id)
            with self.assertRaises(Exception):
                db.execute("""INSERT INTO disruptions(source,event_id,kind,title,shipment_id,detail,severity,created_at)
                    VALUES (?,?,?,?,?,?,?,?)""",('demo-carrier','ILLEGAL-DUP','CARRIER_DELAY','duplicate',1,
                    'same','CRITICAL',e.now()))
        with e.tx() as db:
            self.assertEqual(apply_consolidation(db),[])  # safe to repeat


if __name__=='__main__':
    unittest.main()
