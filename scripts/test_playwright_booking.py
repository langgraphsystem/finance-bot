"""Playwright-based hotel search & booking on booking.com.

Usage:
  python scripts/test_playwright_booking.py                          # Login only
  python scripts/test_playwright_booking.py --search                 # Search hotels
  python scripts/test_playwright_booking.py --search --book 2        # Search + book #2
  python scripts/test_playwright_booking.py --search --details       # Search + open each hotel

Options:
  --city Barcelona          Destination (default: Barcelona)
  --checkin 2026-03-15      Check-in date
  --checkout 2026-03-18     Check-out date
  --adults 2                Adults (default: 2)
  --children 1              Children (default: 0)
  --child-ages 5            Child ages comma-separated
  --rooms 1                 Rooms (default: 1)
  --sort price              Sort: price, rating, distance
  --max-price 200           Max price filter
  --free-cancel             Free cancellation filter
  --details                 Open each hotel for detailed info
  --book N                  Book hotel #N from results
"""

import asyncio
import json
import re
import sys
from pathlib import Path

COOKIES_FILE = Path(__file__).parent / "booking_cookies.json"
RESULT_FILE = Path(__file__).parent / "search_result.json"
LOGIN_URL = "https://account.booking.com/sign-in"
BASE_URL = "https://www.booking.com"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)


def get_arg(name, default=None):
    try:
        idx = sys.argv.index(f"--{name}")
        return sys.argv[idx + 1] if idx + 1 < len(sys.argv) else default
    except ValueError:
        return default


# ── URL Builder ──────────────────────────────────────────────────────────────


def _build_search_url(
    city, checkin, checkout, adults, children, child_ages, rooms,
    sort_by=None, free_cancel=False, max_price=None,
):
    """Build booking.com search URL with all parameters."""
    from urllib.parse import quote

    params = [
        f"ss={quote(city)}",
        f"checkin={checkin}",
        f"checkout={checkout}",
        f"group_adults={adults}",
        f"no_rooms={rooms}",
        f"group_children={children}",
    ]

    # Child ages (each as separate &age= param)
    for age in child_ages:
        params.append(f"age={age}")

    # Sort order
    sort_map = {
        "price": "price",
        "rating": "bayesian_review_score",
        "distance": "distance",
    }
    if sort_by and sort_by in sort_map:
        params.append(f"order={sort_map[sort_by]}")

    # Filters
    nflt_parts = []
    if free_cancel:
        nflt_parts.append("fc=2")
    if max_price:
        nflt_parts.append(f"price=USD-min-{max_price}-1")
    if nflt_parts:
        params.append(f"nflt={'%3B'.join(nflt_parts)}")

    return f"{BASE_URL}/searchresults.html?{'&'.join(params)}"


# ── Login ────────────────────────────────────────────────────────────────────


async def do_login():
    """Launch Chrome, wait for user to login, save cookies."""
    from playwright.async_api import async_playwright

    print(f"\n{'='*60}")
    print(f"  Launching Chrome → {LOGIN_URL}")
    print(f"  Log in manually — I'll detect it automatically.")
    print(f"  Timeout: 2 minutes")
    print(f"{'='*60}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=UA,
        )
        page = await context.new_page()
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")

        print("  Waiting for login... (checking every 3s, max 2 min)\n")

        for attempt in range(40):  # 2 min
            await asyncio.sleep(3)
            cookies = await context.cookies("https://www.booking.com")
            names = {c["name"] for c in cookies}

            # Real login indicators
            has_login = "logintoken" in names or "pcm_personalization" in names
            has_auth = any(
                c["name"] == "bkng_sso_auth" and len(c["value"]) > 50
                for c in cookies
            )

            if has_login or has_auth:
                print(f"  Login detected! ({len(cookies)} cookies)")
                break

            if attempt % 10 == 0:
                print(f"  [{attempt * 3}s] waiting... ({len(cookies)} cookies)")
        else:
            print("  Timeout — saving whatever cookies we have.")

        await asyncio.sleep(2)
        storage_state = await context.storage_state()
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump(storage_state, f, indent=2, ensure_ascii=False)

        booking = [c for c in storage_state["cookies"] if "booking" in c.get("domain", "")]
        print(f"\n  Saved {len(storage_state['cookies'])} cookies ({len(booking)} booking.com)")
        print(f"  File: {COOKIES_FILE}")
        for c in booking[:6]:
            v = c["value"][:30] + "..." if len(c["value"]) > 30 else c["value"]
            print(f"    {c['name']}: {v}")

        await browser.close()


# ── Search ───────────────────────────────────────────────────────────────────


async def do_search():
    """Search hotels on booking.com using Playwright."""
    from playwright.async_api import async_playwright

    if not COOKIES_FILE.exists():
        print("  No cookies. Run without --search first to login.")
        return

    # Parse args
    city = get_arg("city", "Barcelona")
    checkin = get_arg("checkin", "2026-03-15")
    checkout = get_arg("checkout", "2026-03-18")
    adults = int(get_arg("adults", "2"))
    children = int(get_arg("children", "0"))
    child_ages_str = get_arg("child-ages", "")
    child_ages = [int(a) for a in child_ages_str.split(",") if a.strip()] if child_ages_str else []
    rooms = int(get_arg("rooms", "1"))
    sort_by = get_arg("sort")
    max_price = get_arg("max-price")
    free_cancel = "--free-cancel" in sys.argv
    want_details = "--details" in sys.argv
    book_index = get_arg("book")

    print(f"\n{'='*60}")
    print(f"  Search: {city} | {checkin} → {checkout}")
    print(f"  Guests: {adults} adults, {children} children, {rooms} room(s)")
    if child_ages:
        print(f"  Child ages: {child_ages}")
    if sort_by:
        print(f"  Sort: {sort_by}")
    if max_price:
        print(f"  Max price: ${max_price}/night")
    if free_cancel:
        print(f"  Filter: free cancellation")
    print(f"{'='*60}\n")

    with open(COOKIES_FILE, encoding="utf-8") as f:
        storage_state = json.load(f)
    print(f"  Loaded {len(storage_state.get('cookies', []))} cookies")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        context = await browser.new_context(
            storage_state=storage_state,
            viewport={"width": 1280, "height": 900},
            user_agent=UA,
        )
        page = await context.new_page()

        # ── Step 1: Build search URL with all params ──
        print("  [1/5] Building search URL...")
        search_url = _build_search_url(
            city, checkin, checkout, adults, children, child_ages, rooms,
            sort_by=sort_by, free_cancel=free_cancel, max_price=max_price,
        )
        print(f"    URL: {search_url[:120]}...")

        # ── Step 2: Navigate directly to search results ──
        print("  [2/5] Loading search results...")
        await page.goto(search_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Close popups/banners
        for sel in [
            '[aria-label="Dismiss sign-in info."]',
            'button:has-text("Accept")',
            '[id="onetrust-accept-btn-handler"]',
            'button[aria-label="Close"]',
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1000):
                    await btn.click()
                    await page.wait_for_timeout(500)
            except Exception:
                pass

        # ── Step 3: Wait for results ──
        print("  [3/5] Waiting for hotel cards...")
        try:
            await page.wait_for_selector(
                '[data-testid="property-card"]',
                timeout=15000,
            )
        except Exception:
            print("    Results didn't load in 15s, waiting more...")
            await page.wait_for_timeout(5000)

        # ── Step 4: Apply sort if not already in URL ──
        # Sort via URL uses `order=` param which is already set
        # But some sorts need clicking (if URL param didn't work)
        cards = await page.locator('[data-testid="property-card"]').count()
        print(f"    Found {cards} property cards")

        # ── Step 5: Extract results ──
        print("  [5/5] Extracting hotel data...")
        hotels = await _extract_hotels(page)

        if not hotels:
            print("\n  No hotels found! Taking screenshot...")
            await page.screenshot(path="scripts/debug_screenshot.png")
            await browser.close()
            return

        print(f"\n{'='*60}")
        print(f"  FOUND {len(hotels)} HOTELS:")
        print(f"{'='*60}")
        for i, h in enumerate(hotels, 1):
            print(f"\n  {i}. {h['name']}")
            print(f"     Price: {h['price']}")
            print(f"     Rating: {h['rating']} ({h['review_count']} reviews)")
            print(f"     Distance: {h['distance']}")
            if h.get("room_type"):
                print(f"     Room: {h['room_type'][:80]}")
            if h.get("cancellation"):
                print(f"     Cancel: {h['cancellation']}")
            if h.get("url"):
                print(f"     URL: {h['url'][:80]}")

        # ── Details: open each hotel page ──
        if want_details:
            print(f"\n{'='*60}")
            print("  FETCHING DETAILED INFO FOR EACH HOTEL...")
            print(f"{'='*60}")
            for i, h in enumerate(hotels):
                if h.get("url"):
                    details = await _get_hotel_details(context, h["url"])
                    hotels[i].update(details)
                    print(f"\n  {i+1}. {h['name']} — DETAILS:")
                    for k, v in details.items():
                        if v:
                            print(f"     {k}: {v}")

        # Save results
        with open(RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump({"hotels": hotels}, f, indent=2, ensure_ascii=False)
        print(f"\n  Results saved to {RESULT_FILE}")

        # ── Booking ──
        if book_index:
            idx = int(book_index) - 1
            if 0 <= idx < len(hotels) and hotels[idx].get("url"):
                await _do_booking(context, hotels[idx], checkin, checkout, adults, children)
            else:
                print(f"\n  Invalid hotel index: {book_index}")

        await browser.close()


# ── Extract Hotels ───────────────────────────────────────────────────────────


async def _extract_hotels(page, max_results: int = 5) -> list[dict]:
    """Extract hotel data from search results via JS DOM selectors."""
    js = """
    () => {
        const cards = document.querySelectorAll('[data-testid="property-card"]');
        return Array.from(cards).slice(0, %d).map(c => {
            const getText = (sel) => {
                const el = c.querySelector(sel);
                return el ? el.textContent.trim() : '';
            };
            const getLink = () => {
                const a = c.querySelector('a[data-testid="title-link"], a[href*="/hotel/"]');
                return a ? a.href : '';
            };
            const text = c.innerText || '';
            return {
                name: getText('[data-testid="title"]') || getText('h3') || '',
                price: getText('[data-testid="price-and-discounted-price"]') || '',
                rating_raw: getText('[data-testid="review-score"]') || '',
                distance: getText('[data-testid="distance"]') || '',
                room_type: getText('[data-testid="recommended-units"]') || '',
                cancellation: (text.match(/free cancellation|no prepayment/i) || [''])[0],
                breakfast: (text.match(/breakfast included/i) || [''])[0],
                url: getLink(),
            };
        });
    }
    """ % max_results

    raw_hotels = await page.evaluate(js)
    if not raw_hotels:
        return []

    hotels = []
    for h in raw_hotels:
        if not h.get("name"):
            continue

        # Parse rating: "Scored 8.5 8.5Very Good 1,223 reviews" → 8.5, 1223
        rating = ""
        review_count = ""
        rating_raw = h.get("rating_raw", "")
        if rating_raw:
            m = re.search(r"(\d+\.?\d*)", rating_raw)
            if m:
                rating = m.group(1)
            m2 = re.search(r"([\d,]+)\s*review", rating_raw)
            if m2:
                review_count = m2.group(1)

        hotels.append({
            "name": h["name"],
            "price": h["price"],
            "rating": rating,
            "review_count": review_count,
            "distance": h["distance"],
            "room_type": h.get("room_type", ""),
            "cancellation": h.get("cancellation", ""),
            "breakfast": h.get("breakfast", ""),
            "url": h.get("url", ""),
        })

    return hotels


# ── Hotel Details ────────────────────────────────────────────────────────────


async def _get_hotel_details(context, url: str) -> dict:
    """Open a hotel page in new tab and extract detailed info."""
    page = await context.new_page()
    details = {}

    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        js = """
        () => {
            const getText = (sel) => {
                const el = document.querySelector(sel);
                return el ? el.textContent.trim() : '';
            };
            const getAll = (sel) => {
                return Array.from(document.querySelectorAll(sel))
                    .map(e => e.textContent.trim())
                    .filter(t => t.length > 0);
            };

            // Room types and prices
            const rooms = Array.from(
                document.querySelectorAll('tr.js-rt-block-row, [data-testid="room-type"]')
            ).slice(0, 5).map(r => ({
                type: (r.querySelector('.hprt-roomtype-icon-link, [data-testid="room-name"]')
                       || {}).textContent?.trim() || '',
                price: (r.querySelector('.bui-price-display__value, [data-testid="room-price"]')
                        || {}).textContent?.trim() || '',
                occupancy: (r.querySelector('.hprt-occupancy-occupancy-info')
                            || {}).textContent?.trim() || '',
            })).filter(r => r.type);

            // Facilities
            const facilities = getAll(
                '[data-testid="facility-group-icon"] + span, '
                + '.hp_desc_important_facilities span, '
                + '[data-testid="property-most-popular-facilities-wrapper"] span'
            ).slice(0, 15);

            // Description
            const desc = getText(
                '[data-testid="property-description"], '
                + '#property_description_content p'
            );

            // Address
            const address = getText(
                '[data-testid="PropertyHeaderAddressDesktop-text"], '
                + '#showMap2 .hp_address_subtitle'
            );

            // Nearby
            const nearby = getAll(
                '[data-testid="TextSkeleton"] span, '
                + '.hp--popular_landmarks li'
            ).slice(0, 5);

            return {
                rooms: rooms,
                facilities: facilities,
                description: desc ? desc.substring(0, 500) : '',
                address: address,
                nearby: nearby,
                page_url: window.location.href,
            };
        }
        """

        result = await page.evaluate(js)
        if result:
            details = {
                "rooms": result.get("rooms", []),
                "facilities": result.get("facilities", []),
                "description": result.get("description", ""),
                "address": result.get("address", ""),
                "nearby": result.get("nearby", []),
            }
    except Exception as e:
        details["error"] = str(e)
    finally:
        await page.close()

    return details


# ── Booking ──────────────────────────────────────────────────────────────────


async def _do_booking(context, hotel: dict, checkin, checkout, adults, children):
    """Navigate to hotel page → select room → proceed to booking form."""
    print(f"\n{'='*60}")
    print(f"  BOOKING: {hotel['name']}")
    print(f"  URL: {hotel['url'][:80]}")
    print(f"{'='*60}\n")

    page = await context.new_page()
    try:
        await page.goto(hotel["url"], wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Close popups
        for sel in [
            '[aria-label="Dismiss sign-in info."]',
            '[id="onetrust-accept-btn-handler"]',
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1000):
                    await btn.click()
                    await page.wait_for_timeout(500)
            except Exception:
                pass

        # ── Step 1: Scroll to room table and select room quantity ──
        print("  [1/4] Looking for room selection table...")

        # Wait for the room table to load
        room_selects = page.locator('select.hprt-nos-select')
        select_count = await room_selects.count()
        print(f"    Found {select_count} room select dropdowns")

        if select_count == 0:
            # Try alternate selectors
            room_selects = page.locator(
                'select[data-testid="select-room-trigger"], '
                'select[id*="hprt_nos_select"]'
            )
            select_count = await room_selects.count()
            print(f"    Fallback: found {select_count} dropdowns")

        if select_count > 0:
            # Find the recommended room (first one with "Recommended")
            # or just use the first room
            print("  [2/4] Selecting 1 room from first option...")
            first_select = room_selects.first
            await first_select.scroll_into_view_if_needed()
            await page.wait_for_timeout(500)

            # Get available options
            options = await first_select.locator('option').all_text_contents()
            print(f"    Options: {options}")

            # Select "1" (first non-zero option)
            await first_select.select_option("1")
            await page.wait_for_timeout(1000)

            # ── Step 3: Click "I'll reserve" ──
            print("  [3/4] Clicking 'I'll reserve'...")
            reserve_btn = page.locator(
                'button.js-reservation-button, '
                'button:has-text("I\'ll reserve"), '
                'button:has-text("Reserve"), '
                '[data-testid="reservation-cta"]'
            ).first

            if await reserve_btn.is_visible(timeout=5000):
                # Click triggers navigation — wait for it properly
                async with page.expect_navigation(
                    wait_until="domcontentloaded", timeout=30000
                ):
                    await reserve_btn.click()
                print("    Navigated to booking form!")
                await page.wait_for_timeout(3000)
            else:
                print("    Reserve button not found after selecting room!")
        else:
            # No room selects — try direct reserve/book button
            print("  [2/4] No room select dropdowns, trying direct button...")
            reserve_btn = page.locator(
                'button:has-text("Reserve"), '
                'a:has-text("Reserve"), '
                'button:has-text("See availability"), '
                'button:has-text("Book now"), '
                'a:has-text("Book now")'
            ).first
            if await reserve_btn.is_visible(timeout=5000):
                await reserve_btn.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(5000)

        # ── Step 4: Analyze booking/payment page ──
        print("  [4/4] Analyzing booking page...")
        current_url = page.url
        title = await page.title()

        js_check = """
        () => {
            const text = document.body.innerText || '';
            const hasPayment = /credit card|payment details|card number/i.test(text);
            const hasBookerForm = !!document.querySelector(
                'input[name="firstname"], input[name="booker.firstname"], '
                + 'input[name="booker_firstname"], #firstname'
            );
            const hasEmailField = !!document.querySelector(
                'input[name="email"], input[name="booker.email"], '
                + 'input[type="email"]'
            );
            const totalEl = document.querySelector(
                '[data-testid="total-price"], '
                + '.bui-price-display__value, '
                + '.bp-price-details__total-amount, '
                + '.priceIsland__total-price'
            );
            const hasLogin = /sign in|log in|create.*account/i.test(text)
                && !hasBookerForm;

            // Extract pre-filled data
            const firstName = document.querySelector(
                'input[name="firstname"], input[name="booker.firstname"]'
            );
            const lastName = document.querySelector(
                'input[name="lastname"], input[name="booker.lastname"]'
            );
            const email = document.querySelector(
                'input[name="email"], input[name="booker.email"]'
            );

            return {
                has_payment_form: hasPayment,
                has_booking_form: hasBookerForm,
                has_email_field: hasEmailField,
                has_login_prompt: hasLogin,
                total_price: totalEl ? totalEl.textContent.trim() : '',
                page_title: document.title,
                page_url: window.location.href,
                prefilled_first: firstName ? firstName.value : '',
                prefilled_last: lastName ? lastName.value : '',
                prefilled_email: email ? email.value : '',
                is_booking_page: /book|reserv|checkout|payment/i.test(
                    window.location.href
                ),
            };
        }
        """
        check = await page.evaluate(js_check)

        print(f"\n  Current URL: {current_url[:100]}")
        print(f"  Title: {title[:60]}")
        print(f"  Has booking form: {check.get('has_booking_form')}")
        print(f"  Has email field: {check.get('has_email_field')}")
        print(f"  Has payment form: {check.get('has_payment_form')}")
        print(f"  Has login prompt: {check.get('has_login_prompt')}")
        print(f"  Is booking page URL: {check.get('is_booking_page')}")
        if check.get("total_price"):
            print(f"  Total price: {check['total_price']}")
        if check.get("prefilled_first"):
            print(f"  Pre-filled name: {check['prefilled_first']} "
                  f"{check.get('prefilled_last', '')}")
        if check.get("prefilled_email"):
            print(f"  Pre-filled email: {check['prefilled_email']}")

        # Determine status
        if check.get("has_login_prompt") and not check.get("has_booking_form"):
            print(f"\n  LOGIN_REQUIRED — need to log in first")
            status = "LOGIN_REQUIRED"
        elif check.get("has_booking_form") and check.get("has_payment_form"):
            print(f"\n  PAYMENT_REQUIRED — booking form with payment")
            print(f"  Complete manually: {check.get('page_url', current_url)}")
            status = "PAYMENT_REQUIRED"
        elif check.get("has_booking_form"):
            print(f"\n  READY_TO_BOOK — booking form found (no payment yet)")
            status = "READY_TO_BOOK"
        elif check.get("is_booking_page"):
            print(f"\n  BOOKING_PAGE — on booking URL but form not detected")
            print(f"  Complete manually: {check.get('page_url', current_url)}")
            status = "PAYMENT_REQUIRED"
        else:
            print(f"\n  STILL_ON_HOTEL — didn't navigate to booking form")
            status = "RETRY"

        # Save screenshot
        ss_path = Path(__file__).parent / "booking_screenshot.png"
        await page.screenshot(path=str(ss_path))
        print(f"  Screenshot: {ss_path}")

        # Save booking result
        result_path = Path(__file__).parent / "booking_result.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump({
                "hotel": hotel,
                "status": status,
                "booking_url": check.get("page_url", current_url),
                "check": check,
            }, f, indent=2, ensure_ascii=False)
        print(f"  Result: {result_path}")

    except Exception as e:
        print(f"\n  BOOKING ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await page.close()


# ── Main ─────────────────────────────────────────────────────────────────────


async def main():
    if "--search" in sys.argv:
        await do_search()
    else:
        await do_login()
        print("\n  Now run: python scripts/test_playwright_booking.py --search")


if __name__ == "__main__":
    asyncio.run(main())
