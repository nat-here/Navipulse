"""Python-only external webhook test: python scripts/send_webhook.py"""
import json
import os
import sys
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta, timezone

base=os.getenv("DISRUPTION_BACKEND_URL","http://localhost:8000")
key=os.getenv("CARRIER_WEBHOOK_TOKEN","")
if not key:
    raise SystemExit("Set CARRIER_WEBHOOK_TOKEN before sending")
now=datetime.now(timezone.utc)
revision=int(sys.argv[1]) if len(sys.argv)>1 else 1
payload={"event_id":f"carrier-demo-{revision}","tracking":"SHP-1001","revision":revision,
         "eta":(now+timedelta(days=8)).isoformat(),"occurred_at":now.isoformat()}
req=urllib.request.Request(base.rstrip("/")+"/carrier/webhook",json.dumps(payload).encode(),
    headers={"Content-Type":"application/json","x-carrier-token":key},method="POST")
with urllib.request.urlopen(req,timeout=10) as response:
    print(response.status, response.read().decode())
