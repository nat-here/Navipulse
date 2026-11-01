"""ASGI carrier endpoint security tests, no HTTP server / third-party packages."""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from disruption_iq import engine as e
from disruption_iq.webhook import carrier_api


class WebhookAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=e.DB_PATH
        e.DB_PATH=Path(self.temp.name)/"asgi.db"
        e.init_db()

    def tearDown(self):
        e.DB_PATH=self.old
        self.temp.cleanup()

    def post(self, token, data):
        buffer=[]
        async def inner(scope,receive,send):
            raise AssertionError("Webhook should intercept request")
        api=carrier_api(inner)
        async def receive():
            return {"type":"http.request","body":data,"more_body":False}
        async def send(msg):buffer.append(msg)
        with patch.dict(os.environ,{"CARRIER_WEBHOOK_TOKEN":"only-tests-secret"}):
            asyncio.run(api({"type":"http","path":"/carrier/webhook","method":"POST",
               "headers":[(b"x-carrier-token",token.encode())]},receive,send))
        return buffer[0]["status"],json.loads(buffer[-1]["body"])

    def test_unsigned_request_does_not_mutate(self):
        status,result=self.post("invalid",b"{}")
        self.assertEqual(status,401)
        with e.read_db() as con:
            self.assertEqual(e.one(con,"SELECT count(*) AS n FROM disruptions")["n"],0)

    def test_authenticated_webhook_idempotent(self):
        payload={"event_id":"asgi-1","tracking":"SHP-1001","revision":1,
                 "eta":e.days_from_today(8),"occurred_at":e.now()}
        raw=json.dumps(payload).encode()
        status,outcome=self.post("only-tests-secret",raw)
        self.assertEqual((status,outcome["outcome"]),(200,"APPLIED"))
        status,outcome=self.post("only-tests-secret",raw)
        self.assertEqual((status,outcome["outcome"]),(200,"DUPLICATE"))
        status,outcome=self.post("only-tests-secret",json.dumps({**payload,"eta":e.days_from_today(11)}).encode())
        self.assertEqual(status,422)


if __name__=="__main__":unittest.main()
