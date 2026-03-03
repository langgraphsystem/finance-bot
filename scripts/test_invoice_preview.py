"""Quick test: send invoice request, verify preview+buttons flow."""

import asyncio
import json
import os
import sys
import time
import warnings
from pathlib import Path

from dotenv import load_dotenv

ROOT = str(Path(__file__).parent.parent)
sys.path.insert(0, ROOT)
load_dotenv(Path(ROOT) / ".env", override=True)
os.environ["APP_ENV"] = "testing"
warnings.filterwarnings("ignore")


class FakeRedis:
    def __init__(self):
        self._store: dict = {}
        self._lists: dict = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ex=None):
        self._store[key] = value

    async def delete(self, *keys):
        for k in keys:
            self._store.pop(k, None)
            self._lists.pop(k, None)

    async def incr(self, key):
        self._store[key] = int(self._store.get(key, 0)) + 1
        return self._store[key]

    async def expire(self, key, ttl):
        pass

    async def exists(self, key):
        return 1 if key in self._store or key in self._lists else 0

    async def ttl(self, key):
        return -1

    async def rpush(self, key, *values):
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].extend(values)

    async def lrange(self, key, start, end):
        lst = self._lists.get(key, [])
        if end == -1:
            return lst[start:]
        return lst[start : end + 1]

    async def ltrim(self, key, start, end):
        lst = self._lists.get(key, [])
        if end == -1:
            self._lists[key] = lst[start:]
        else:
            self._lists[key] = lst[start : end + 1]

    async def llen(self, key):
        return len(self._lists.get(key, []))

    async def setex(self, key, ttl, value):
        self._store[key] = value

    async def setnx(self, key, value):
        if key not in self._store:
            self._store[key] = value
            return True
        return False

    async def keys(self, pattern="*"):
        return list(self._store.keys()) + list(self._lists.keys())


async def main():
    import src.core.db as db_module

    fake_redis = FakeRedis()
    db_module.redis = fake_redis

    import src.core.router as router_module

    if hasattr(router_module, "redis"):
        router_module.redis = fake_redis

    import src.skills.generate_invoice.handler as inv_handler

    inv_handler.redis = fake_redis

    from unittest.mock import AsyncMock, patch

    from api.main import build_session_context
    from src.core.router import handle_message
    from src.gateway.types import IncomingMessage, MessageType

    chat_id = "7314014306"
    print("Building session context...")
    context = await build_session_context(chat_id)
    if not context:
        print("ERROR: User not found")
        return

    print(f"Context: user_id={context.user_id}, lang={context.language}, currency={context.currency}")

    # Mock contact since DB has none yet
    fake_contact = {
        "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "name": "Mike Chen",
        "email": "mike@example.com",
        "phone": "555-1234",
    }

    text = "create invoice for Mike Chen for plumbing repair $500 and pipe installation $150"
    msg = IncomingMessage(
        id=f"test-{int(time.time())}",
        user_id=chat_id,
        chat_id=chat_id,
        type=MessageType.text,
        text=text,
        channel="telegram",
        language="en",
    )

    print(f"\nSending: {text}")
    print("=" * 60)
    t0 = time.perf_counter()
    with patch(
        "src.skills.generate_invoice.handler._find_contact",
        new_callable=AsyncMock,
        return_value=fake_contact,
    ):
        response = await handle_message(msg, context)
    t1 = time.perf_counter()

    print(f"Response time: {int((t1 - t0) * 1000)}ms")
    print(f"\nResponse text:\n{response.text}")
    print(f"\nHas buttons: {bool(response.buttons)}")
    if response.buttons:
        for i, b in enumerate(response.buttons):
            bt = b["text"]
            bc = b["callback"]
            print(f"  Button {i + 1}: text={bt!r}, callback={bc!r}")
    print(f"Has document: {bool(response.document)}")
    if response.document:
        print(f"  Document name: {response.document_name}")
        print(f"  Document size: {len(response.document)} bytes")

    # Check pending invoice in Redis
    for k, v in fake_redis._store.items():
        if "invoice_pending" in k:
            data = json.loads(v)
            sym = data.get("currency_symbol", "$")
            print(f"\n--- Pending invoice in Redis ({k}) ---")
            print(f"  invoice_number: {data.get('invoice_number')}")
            print(f"  client_name: {data.get('client_name')}")
            print(f"  client_email: {data.get('client_email')}")
            print(f"  total: {sym}{data.get('total')}")
            print(f"  due_date: {data.get('due_date')}")
            print(f"  company_name: {data.get('company_name')}")
            items = data.get("items", [])
            print(f"  items ({len(items)}):")
            for item in items:
                desc = item["description"]
                qty = item.get("quantity", 1)
                unit = item.get("unit_price", 0)
                amt = item.get("amount", 0)
                print(f"    - {desc}: qty={qty}, unit={sym}{unit}, total={sym}{amt}")


if __name__ == "__main__":
    asyncio.run(main())
