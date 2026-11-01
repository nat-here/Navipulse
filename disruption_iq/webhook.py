"""Pure Python ASGI ingress attached to Reflex's API transformer.
No separate web framework import or dependency. Example POST /carrier/webhook.
"""
import hmac
import json
import os
from .engine import ingest_carrier

MAX_BODY=16384


def carrier_api(inner):
    async def app(scope, receive, send):
        if scope.get("type")!="http" or scope.get("path")!="/carrier/webhook":
            await inner(scope,receive,send)
            return
        async def reply(status, data):
            raw=json.dumps(data).encode()
            await send({"type":"http.response.start","status":status,
                        "headers":[(b"content-type",b"application/json"),(b"cache-control",b"no-store")]})
            await send({"type":"http.response.body","body":raw})
        if scope.get("method")!="POST":
            await reply(405,{"error":"POST required"});return
        headers={k.lower():v for k,v in scope.get("headers",[])}
        expected=os.getenv("CARRIER_WEBHOOK_TOKEN")
        if not expected or not hmac.compare_digest(headers.get(b"x-carrier-token",b""),expected.encode()):
            await reply(401,{"error":"Unauthorized carrier token"});return
        body=b""
        while True:
            msg=await receive()
            if msg["type"]=="http.disconnect":return
            body+=msg.get("body",b"")
            if len(body)>MAX_BODY:
                await reply(413,{"error":"Payload too large"});return
            if not msg.get("more_body",False):break
        try:
            payload=json.loads(body)
            output=ingest_carrier(payload,source="carrier-webhook")
            await reply(200,output)
        except (ValueError,TypeError) as exc:
            await reply(422,{"error":str(exc)})
        except Exception:
            await reply(500,{"error":"Webhook processing failed"})
    return app
