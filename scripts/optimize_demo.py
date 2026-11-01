"""Run the deterministic what-if scenario without installing/running Reflex.

From project root: python scripts/optimize_demo.py --demo-events --budget 1500 --transfer 70
Without --demo-events this is a read-only optimization of existing disruptions.
"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from disruption_iq import engine

parser=argparse.ArgumentParser()
parser.add_argument('--demo-events',action='store_true',help='Seed the synthetic disruption scenarios before optimization')
parser.add_argument('--profile',choices=['BALANCED','SLA_FIRST','COST_FIRST'],default='BALANCED')
parser.add_argument('--budget',type=int,default=30000)
parser.add_argument('--transfer',type=int,default=120)
args=parser.parse_args()
engine.init_db()
analyst=engine.login('analyst','Analyst#2026')['id']
if args.demo_events:
    for scenario in (engine.scenario_carrier,engine.scenario_supplier,engine.scenario_stock):
        try:
            print('Synthetic event:',scenario(analyst)['outcome'])
        except ValueError as ex:
            print('Existing scenario not changed:',str(ex))
result=engine.preview_optimization(analyst,args.profile,args.budget,args.transfer)
print('\nOPTIMIZED SCENARIO:',result['profile'])
print('Affected orders:',result['examined'],'Selected:',result['recovered_orders'],
      'On-time:',result['sla_met'],'Transfer units:',result['transferred'])
print('MODELED avoidance: $',result['saved'],'Recovery cost: $',result['cost'],
      'MODELED net: $',result['net'])
print('Shared resource conflicts:')
for conflict in result['conflicts']:
    print(' -', conflict['resource'],conflict['contenders'],'free:',conflict['capacity'])
print('Selected recovery allocations:')
for action in result['picks']:
    print(' -',action['order_no'],action['kind'],action['qty'],'units',
          action['source'],action['sla_note'],'cost $',action['cost'])
print('\nREAD-ONLY: no approval, shipment, supplier or inventory records modified.')
print('The 18%-of-contract risk-weighted avoided-loss proxy is synthetic, not an actual penalty.')
