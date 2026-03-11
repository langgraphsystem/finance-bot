r"""Launch real Google Chrome for Amazon Relay login and upload the session directly.

Usage:
  .\.venv\Scripts\python.exe scripts\launch_relay_chrome_setup.py ^
    --api-url https://your-app.up.railway.app ^
    --token your-extension-token

This flow does not require installing a Chrome extension.

It opens real Google Chrome with a dedicated profile and remote debugging,
waits for you to finish the Amazon Relay login manually, then reads cookies
from Chrome and uploads them to the existing browser-session API.
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from playwright.async_api import Browser, BrowserContext, Error, Page, async_playwright

DEFAULT_CHROME_PATH = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
DEFAULT_PROVIDER = "relay.amazon.com"
DEFAULT_PROFILE_DIR = Path.home() / "AppData" / "Local" / "Temp" / "finance-bot-relay-direct-login"
AUTH_PATH_HINTS = (
    "/login",
    "/signin",
    "/sign-in",
    "/auth",
    "/challenge",
    "/verify",
    "/mfa",
    "/otp",
    "/ap/signin",
)
COOKIE_DOMAINS = ("relay.amazon.com", "amazon.com")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch real Chrome, wait for Amazon Relay login, and upload cookies.",
    )
    parser.add_argument("--api-url", required=True, help="Finance Bot public base URL")
    parser.add_argument("--token", required=True, help="Bearer token from the bot /extension flow")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, help="Provider domain")
    parser.add_argument(
        "--chrome-path",
        default=str(DEFAULT_CHROME_PATH),
        help="Path to chrome.exe",
    )
    parser.add_argument(
        "--profile-dir",
        default=str(DEFAULT_PROFILE_DIR),
        help="Dedicated Chrome profile directory for this flow",
    )
    parser.add_argument(
        "--debug-port",
        type=int,
        default=9223,
        help="Remote debugging port for Chrome",
    )
    parser.add_argument(
        "--timeout-minutes",
        type=int,
        default=20,
        help="How long to wait for manual login before timing out",
    )
    return parser.parse_args()


def normalize_api_url(value: str) -> str:
    trimmed = value.strip().rstrip("/")
    if trimmed.endswith("/webhook"):
        return trimmed[: -len("/webhook")]
    if trimmed.endswith("/api/ext"):
        return trimmed[: -len("/api/ext")]
    return trimmed


def normalize_domain(value: str) -> str:
    raw = value.strip().lower()
    if "://" in raw:
        raw = urlparse(raw).hostname or raw
    domain = raw.split("/")[0].removeprefix("www.")
    if domain == "relay.amazon.com" or domain.endswith(".relay.amazon.com"):
        return "relay.amazon.com"
    return domain


def is_auth_like(url: str) -> bool:
    path = (urlparse(url).path or "").lower()
    return any(hint in path for hint in AUTH_PATH_HINTS)


def is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def convert_cookie(cookie: dict) -> dict:
    same_site = str(cookie.get("sameSite", "Lax"))
    if same_site.lower() == "unspecified":
        same_site = "None"
    elif same_site:
        same_site = same_site[0].upper() + same_site[1:]
    return {
        "name": cookie["name"],
        "value": cookie["value"],
        "domain": cookie["domain"],
        "path": cookie.get("path", "/"),
        "expires": cookie.get("expires", -1),
        "httpOnly": bool(cookie.get("httpOnly", False)),
        "secure": bool(cookie.get("secure", False)),
        "sameSite": same_site or "None",
    }


def launch_chrome(chrome_path: Path, profile_dir: Path, port: int) -> subprocess.Popen:
    profile_dir.mkdir(parents=True, exist_ok=True)
    args = [
        str(chrome_path),
        f"--user-data-dir={profile_dir}",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        "https://relay.amazon.com/",
    ]
    return subprocess.Popen(args)


async def wait_for_cdp(port: int, timeout_seconds: int = 20) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if is_port_open(port):
            return
        await asyncio.sleep(0.5)
    raise TimeoutError(f"Chrome remote debugging port {port} did not open in time")


async def connect_browser(port: int) -> tuple[Browser, BrowserContext]:
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
    except Exception:
        await playwright.stop()
        raise

    context = browser.contexts[0]
    browser._playwright = playwright  # type: ignore[attr-defined]
    return browser, context


async def disconnect_browser(browser: Browser) -> None:
    playwright = getattr(browser, "_playwright", None)
    if playwright is not None:
        await playwright.stop()


async def get_active_page(context: BrowserContext) -> Page:
    if context.pages:
        return context.pages[-1]
    return await context.new_page()


async def collect_relay_cookies(context: BrowserContext) -> list[dict]:
    cookies = await context.cookies(*[f"https://{domain}/" for domain in COOKIE_DOMAINS])
    seen: set[tuple[str, str, str]] = set()
    result: list[dict] = []
    for cookie in cookies:
        key = (cookie["name"], cookie["domain"], cookie.get("path", "/"))
        if key in seen:
            continue
        seen.add(key)
        result.append(convert_cookie(cookie))
    return result


async def save_session(api_url: str, token: str, cookies: list[dict]) -> dict:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{api_url}/api/ext/session",
            headers={"Authorization": f"Bearer {token}"},
            json={"site": DEFAULT_PROVIDER, "cookies": cookies},
        )
        response.raise_for_status()
        return response.json()


async def get_status(api_url: str, token: str) -> dict:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{api_url}/api/ext/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json()


async def wait_for_login_and_save(
    context: BrowserContext,
    api_url: str,
    token: str,
    timeout_minutes: int,
) -> bool:
    deadline = time.time() + (timeout_minutes * 60)
    while time.time() < deadline:
        page = await get_active_page(context)
        current_url = page.url
        domain = normalize_domain(current_url)
        cookies = await collect_relay_cookies(context)

        if (
            cookies
            and domain == DEFAULT_PROVIDER
            and not is_auth_like(current_url)
        ):
            saved = await save_session(api_url, token, cookies)
            status = await get_status(api_url, token)
            print("\nAmazon Relay session saved.")
            print(f"Saved site: {saved.get('site', DEFAULT_PROVIDER)}")
            print(f"Cookie count: {len(cookies)}")
            if status.get("bot_username"):
                print(f"Telegram: https://t.me/{status['bot_username']}?start=browser_connect")
            return True

        await asyncio.sleep(3)

    return False


async def main() -> int:
    args = parse_args()
    chrome_path = Path(args.chrome_path)
    profile_dir = Path(args.profile_dir)
    api_url = normalize_api_url(args.api_url)

    if not chrome_path.exists():
        print(f"Google Chrome not found: {chrome_path}")
        return 1

    process = launch_chrome(chrome_path, profile_dir, args.debug_port)
    browser: Browser | None = None
    print("Launched real Google Chrome.")
    print(f"Profile: {profile_dir}")
    print("Log in to Amazon Relay in the opened Chrome window.")

    try:
        await wait_for_cdp(args.debug_port)
        browser, context = await connect_browser(args.debug_port)
    except Exception as exc:
        print(f"Failed to connect to Chrome: {exc}")
        return 1

    try:
        success = await wait_for_login_and_save(
            context=context,
            api_url=api_url,
            token=args.token,
            timeout_minutes=args.timeout_minutes,
        )
        if not success:
            print("\nTimed out waiting for Amazon Relay login.")
            return 2
        return 0
    except httpx.HTTPStatusError as exc:
        print(f"API error: {exc.response.status_code} {exc.response.text}")
        return 1
    except Error as exc:
        print(f"Browser automation error: {exc}")
        return 1
    finally:
        if browser is not None:
            await disconnect_browser(browser)
        if process.poll() is None:
            print("\nChrome is still open in the dedicated profile.")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
