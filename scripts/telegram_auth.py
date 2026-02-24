"""Telethon auth — two-phase, non-interactive for CLI automation.

Usage:
    # Phase 1: request code
    python scripts/telegram_auth.py --phone +1234567890

    # Phase 2: sign in with code (received via Telegram)
    python scripts/telegram_auth.py --code 12345

    # If 2FA enabled:
    python scripts/telegram_auth.py --password YOUR_2FA_PASSWORD

    # Interactive (run from terminal manually):
    python scripts/telegram_auth.py
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION_PATH = str(Path(__file__).parent / "test_telegram")
STATE_FILE = Path(__file__).parent / ".telethon_auth_state.json"


async def request_code(phone: str):
    """Phase 1: Send sign-in code request."""
    from telethon import TelegramClient

    client = TelegramClient(SESSION_PATH, int(API_ID), API_HASH)
    await client.connect()

    result = await client.send_code_request(phone)

    # Save state for phase 2
    STATE_FILE.write_text(
        json.dumps({"phone": phone, "phone_code_hash": result.phone_code_hash}),
        encoding="utf-8",
    )

    print(f"Code sent to {phone}")
    print(f"Check Telegram for the verification code.")
    print(f"Then run: python scripts/telegram_auth.py --code XXXXX")

    await client.disconnect()


async def sign_in_with_code(code: str):
    """Phase 2: Complete sign-in with the received code."""
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError

    if not STATE_FILE.exists():
        print("ERROR: No pending auth. Run --phone first.")
        return False

    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    phone = state["phone"]
    phone_code_hash = state["phone_code_hash"]

    client = TelegramClient(SESSION_PATH, int(API_ID), API_HASH)
    await client.connect()

    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        me = await client.get_me()
        print(f"Success! Logged in as: {me.first_name} {me.last_name or ''} (id={me.id})")
        print(f"Session saved: {SESSION_PATH}.session")
        STATE_FILE.unlink(missing_ok=True)
        await client.disconnect()
        return True
    except SessionPasswordNeededError:
        print("2FA password required. Run: python scripts/telegram_auth.py --password YOUR_PASSWORD")
        await client.disconnect()
        return False


async def sign_in_with_password(password: str):
    """Phase 2b: Complete sign-in with 2FA password."""
    from telethon import TelegramClient

    client = TelegramClient(SESSION_PATH, int(API_ID), API_HASH)
    await client.connect()

    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        print(f"Success! Logged in as: {me.first_name} {me.last_name or ''} (id={me.id})")
        print(f"Session saved: {SESSION_PATH}.session")
        STATE_FILE.unlink(missing_ok=True)
        await client.disconnect()
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        await client.disconnect()
        return False


async def interactive():
    """Full interactive auth (for running from terminal)."""
    from telethon import TelegramClient

    client = TelegramClient(SESSION_PATH, int(API_ID), API_HASH)
    print("Connecting to Telegram...")
    await client.start()
    me = await client.get_me()
    print(f"Success! Logged in as: {me.first_name} {me.last_name or ''} (id={me.id})")
    print(f"Session saved: {SESSION_PATH}.session")
    await client.disconnect()


def main():
    if not API_ID or not API_HASH:
        print("ERROR: TELEGRAM_API_ID and TELEGRAM_API_HASH not found in .env")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Telethon auth helper")
    parser.add_argument("--phone", help="Phone number to request code (e.g., +1234567890)")
    parser.add_argument("--code", help="Verification code from Telegram")
    parser.add_argument("--password", help="2FA password")
    args = parser.parse_args()

    if args.phone:
        asyncio.run(request_code(args.phone))
    elif args.code:
        asyncio.run(sign_in_with_code(args.code))
    elif args.password:
        asyncio.run(sign_in_with_password(args.password))
    else:
        asyncio.run(interactive())


if __name__ == "__main__":
    main()
