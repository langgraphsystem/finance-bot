r"""Launch real Google Chrome with the Finance Bot extension and open Amazon Relay connect flow.

Usage:
  .\.venv\Scripts\python.exe scripts\launch_relay_chrome_setup.py ^
    --api-url https://your-app.up.railway.app ^
    --token your-extension-token

The script launches the installed Google Chrome browser (not bundled Chromium),
loads the local browser extension, opens its popup page, stores API settings,
and clicks "Connect Amazon Relay". You then complete the Relay login manually.
When the extension saves the session and redirects to Telegram, the script reports it.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
from pathlib import Path
from urllib.parse import quote

DEFAULT_CHROME_PATH = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
DEFAULT_PROVIDER = "relay.amazon.com"
SUCCESS_MARKER = "start=browser_connect"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Launch real Google Chrome with the Finance Bot extension and "
            "open Amazon Relay."
        ),
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("FINANCE_BOT_API_URL", "").strip(),
        help="Finance Bot public base URL, for example https://your-app.up.railway.app",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("FINANCE_BOT_EXTENSION_TOKEN", "").strip(),
        help="Extension token from the bot /extension flow",
    )
    parser.add_argument(
        "--provider",
        default=DEFAULT_PROVIDER,
        help="Provider domain to connect. Default: relay.amazon.com",
    )
    parser.add_argument(
        "--chrome-path",
        default=str(DEFAULT_CHROME_PATH),
        help="Path to real Google Chrome executable",
    )
    parser.add_argument(
        "--timeout-minutes",
        type=int,
        default=20,
        help="How long to wait for Telegram redirect before exiting",
    )
    return parser.parse_args()


def build_user_data_dir() -> str:
    profile_dir = Path(tempfile.gettempdir()) / "finance-bot-relay-chrome"
    profile_dir.mkdir(parents=True, exist_ok=True)
    return str(profile_dir)


async def resolve_extension_id(context) -> str:
    worker = context.service_workers[0] if context.service_workers else None
    if worker is None:
        worker = await context.wait_for_event("serviceworker")
    return worker.url.split("/")[2]


async def configure_extension_popup(popup_page, api_url: str, token: str) -> None:
    await popup_page.goto(popup_page.url, wait_until="domcontentloaded")
    await popup_page.locator("#apiUrl").fill(api_url)
    await popup_page.locator("#token").fill(token)
    await popup_page.locator("#saveApiBtn").click()
    await popup_page.wait_for_timeout(800)
    await popup_page.locator("#connectAmazonRelayBtn").click()


async def wait_for_success(context, timeout_minutes: int) -> bool:
    deadline = asyncio.get_running_loop().time() + (timeout_minutes * 60)
    while asyncio.get_running_loop().time() < deadline:
        for page in context.pages:
            url = page.url
            if SUCCESS_MARKER in url:
                print("\nRelay session saved. Chrome redirected to Telegram.")
                print(f"Current URL: {url}")
                return True
        await asyncio.sleep(2)
    return False


async def main() -> int:
    args = parse_args()
    chrome_path = Path(args.chrome_path)
    extension_dir = Path(__file__).resolve().parent.parent / "browser-extension"

    if not chrome_path.exists():
        print(f"Google Chrome not found: {chrome_path}")
        return 1
    if not args.api_url or not args.token:
        print("Both --api-url and --token are required.")
        return 1

    from playwright.async_api import async_playwright

    user_data_dir = build_user_data_dir()
    provider = quote(args.provider, safe="")

    print("Launching real Google Chrome...")
    print(f"Chrome: {chrome_path}")
    print(f"Extension: {extension_dir}")
    print(f"Profile dir: {user_data_dir}")

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            executable_path=str(chrome_path),
            headless=False,
            args=[
                f"--disable-extensions-except={extension_dir}",
                f"--load-extension={extension_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        try:
            extension_id = await resolve_extension_id(context)
            popup_url = f"chrome-extension://{extension_id}/popup.html"
            popup_page = await context.new_page()
            await popup_page.goto(popup_url, wait_until="domcontentloaded")
            await configure_extension_popup(popup_page, args.api_url, args.token)

            connect_url = f"{args.api_url.rstrip('/')}/api/ext/connect?provider={provider}"
            print("\nPopup configured.")
            print(f"Connect URL: {connect_url}")
            print("Finish the Amazon Relay login in the real Chrome window.")
            print("The script will wait for Telegram redirect to confirm success.")

            success = await wait_for_success(context, args.timeout_minutes)
            if not success:
                print("\nTimeout waiting for Telegram redirect.")
                print("If the browser is still open, you can continue the login manually.")
                return 2

            await asyncio.sleep(3)
            return 0
        finally:
            await context.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
