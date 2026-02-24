"""Playwright-based hotel search & booking on booking.com.

Usage:
  python scripts/test_playwright_booking.py                          # Login only
  python scripts/test_playwright_booking.py --search                 # Search hotels
  python scripts/test_playwright_booking.py --search --book 2        # Search + book #2
  python scripts/test_playwright_booking.py --search --details       # Search + open each hotel
  python scripts/test_playwright_booking.py --full                   # Full flow (login→search→book)
  python scripts/test_playwright_booking.py --full --use-saved-card  # + complete with saved card
  python scripts/test_playwright_booking.py --full --use-saved-card --cancel-booking  # + cancel

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
  --complete                Complete booking (in --search mode)
  --use-saved-card          Complete booking with saved card (in --full mode)
  --cancel-booking          Cancel after booking
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
    print("  Log in manually — I'll detect it automatically.")
    print("  Timeout: 2 minutes")
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

        print("  Waiting for login... (checking every 3s, max 3 min)")
        print("  Login is detected when the page leaves sign-in URL\n")

        for attempt in range(60):  # 3 min
            await asyncio.sleep(3)

            # Check if page navigated away from sign-in
            current_url = page.url
            left_signin = (
                "sign-in" not in current_url
                and "signin" not in current_url
                and "login" not in current_url
            )

            # Also check cookies
            cookies = await context.cookies("https://www.booking.com")
            names = {c["name"] for c in cookies}
            has_login_cookie = (
                "logintoken" in names or "pcm_personalization" in names
            )

            if left_signin or has_login_cookie:
                print(f"  Login detected! Page: {current_url[:60]}")
                print(f"  Cookies: {len(cookies)}")
                # Wait a bit for all cookies to settle
                await asyncio.sleep(3)
                break

            if attempt % 10 == 0:
                elapsed = attempt * 3
                print(f"  [{elapsed}s] waiting... "
                      f"(page: {'sign-in' if not left_signin else 'other'}, "
                      f"{len(cookies)} cookies)")
        else:
            print("  Timeout (3 min) — saving whatever cookies we have.")

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
        print("  Filter: free cancellation")
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
        return Array.from(cards).slice(0, MAX_N).map(c => {
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
    """.replace("MAX_N", str(max_results))

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
                try:
                    async with page.expect_navigation(
                        wait_until="domcontentloaded", timeout=15000
                    ):
                        await reserve_btn.click()
                    print("    Navigated to booking form!")
                except Exception:
                    print("    Click done (no navigation event)")
                await page.wait_for_timeout(3000)
                # Verify we're on booking page
                if "book" in page.url.lower():
                    print(f"    On booking page: {page.url[:80]}")
                else:
                    # Wait more for redirect
                    await page.wait_for_timeout(5000)
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
            print("\n  LOGIN_REQUIRED — need to log in first")
            status = "LOGIN_REQUIRED"
        elif check.get("has_booking_form") and check.get("has_payment_form"):
            print("\n  PAYMENT_REQUIRED — booking form with payment")
            print(f"  Complete manually: {check.get('page_url', current_url)}")
            status = "PAYMENT_REQUIRED"
        elif check.get("has_booking_form"):
            print("\n  READY_TO_BOOK — booking form found (no payment yet)")
            status = "READY_TO_BOOK"
        elif check.get("is_booking_page"):
            print("\n  BOOKING_PAGE — on booking URL but form not detected")
            print(f"  Complete manually: {check.get('page_url', current_url)}")
            status = "PAYMENT_REQUIRED"
        else:
            print("\n  STILL_ON_HOTEL — didn't navigate to booking form")
            status = "RETRY"

        # Save screenshot
        ss_path = Path(__file__).parent / "booking_screenshot.png"
        await page.screenshot(path=str(ss_path), full_page=True)
        print(f"  Screenshot: {ss_path}")

        # ── Fill empty required fields if needed ──
        if status == "READY_TO_BOOK" and not check.get("prefilled_first"):
            print("\n  Form fields empty — filling required fields...")
            await _fill_booking_form(page, check)
            await page.wait_for_timeout(1000)

        # ── Complete booking if --complete flag ──
        if "--complete" in sys.argv and status == "READY_TO_BOOK":
            confirmation = await _complete_booking(page)
            status = confirmation.get("status", status)
            check.update(confirmation)

            # ── Cancel booking if --cancel-booking flag ──
            if "--cancel-booking" in sys.argv and status == "CONFIRMED":
                cancel_result = await _cancel_booking(
                    page, context, confirmation
                )
                check.update(cancel_result)

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


async def _fill_booking_form(page, check: dict):
    """Fill required booking form fields if they're empty."""
    # Try to get user data from previous check or use defaults
    first_name = check.get("prefilled_first", "")
    last_name = check.get("prefilled_last", "")
    email = check.get("prefilled_email", "")

    # Fill first name
    fn_field = page.locator(
        'input[name="firstname"], input[name="booker.firstname"], #firstname'
    ).first
    if await fn_field.is_visible(timeout=2000):
        current = await fn_field.input_value()
        if not current.strip():
            if not first_name:
                # Try to get from saved cookies/profile
                first_name = "Manas"  # From previous session
            await fn_field.fill(first_name)
            print(f"    Filled first name: {first_name}")

    # Fill last name
    ln_field = page.locator(
        'input[name="lastname"], input[name="booker.lastname"], #lastname'
    ).first
    if await ln_field.is_visible(timeout=2000):
        current = await ln_field.input_value()
        if not current.strip():
            if not last_name:
                last_name = "Manapbaev"
            await ln_field.fill(last_name)
            print(f"    Filled last name: {last_name}")

    # Fill email
    em_field = page.locator(
        'input[name="email"], input[name="booker.email"], '
        'input[type="email"]'
    ).first
    if await em_field.is_visible(timeout=2000):
        current = await em_field.input_value()
        if not current.strip():
            if not email:
                email = "manas.manapbaev1985@gmail.com"
            await em_field.fill(email)
            print(f"    Filled email: {email}")

    # Fill country if empty
    country_field = page.locator(
        'select[name="cc1"], select[name="booker.country"]'
    ).first
    if await country_field.is_visible(timeout=2000):
        try:
            current_val = await country_field.input_value()
            if not current_val or current_val == "":
                await country_field.select_option("kg")  # Kyrgyzstan
                print("    Filled country: Kyrgyzstan")
        except Exception:
            pass

    # Fill phone if empty
    phone_field = page.locator(
        'input[name="phone"], input[name="booker.phone"], '
        'input[name="telephone"]'
    ).first
    if await phone_field.is_visible(timeout=2000):
        current = await phone_field.input_value()
        if not current.strip():
            await phone_field.fill("0552030766")
            print("    Filled phone: 0552030766")

    await page.wait_for_timeout(500)

    # Click "Show fields" to reveal any hidden required fields
    show_fields = page.locator('button:has-text("Show fields")').first
    try:
        if await show_fields.is_visible(timeout=1000):
            await show_fields.click()
            await page.wait_for_timeout(500)
            print("    Clicked 'Show fields' to reveal missing fields")
    except Exception:
        pass


async def _complete_booking(page) -> dict:
    """Advance through booking form steps, detect payment/saved card."""
    print(f"\n{'='*60}")
    print("  ADVANCING THROUGH BOOKING STEPS...")
    print(f"{'='*60}\n")

    result = {"status": "READY_TO_BOOK"}

    # Booking.com has 3 steps: 1-Selection → 2-Your Details → 3-Finish booking
    # We need to click through each step's primary button
    for step in range(4):
        # Scroll to bottom to find the action button
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000)

        # Find any primary action button
        btn = page.locator(
            'button:has-text("Next: Final details"), '
            'button:has-text("Final details"), '
            'button:has-text("Complete booking"), '
            'button:has-text("Complete Booking"), '
            'button:has-text("Book now"), '
            'button:has-text("Finish booking")'
        ).first

        if not await btn.is_visible(timeout=5000):
            print(f"  Step {step + 1}: No action button found")
            break

        btn_text = (await btn.text_content()).strip()
        print(f"  Step {step + 1}: Found '{btn_text}'")

        # Scroll button into view and click
        await btn.scroll_into_view_if_needed()
        await page.wait_for_timeout(500)

        is_complete = any(
            w in btn_text.lower()
            for w in ("complete", "finish", "book now")
        )

        print("    Clicking...")
        try:
            async with page.expect_navigation(
                wait_until="domcontentloaded", timeout=15000
            ):
                await btn.click()
            print(f"    Navigated to: {page.url[:80]}")
        except Exception:
            # No navigation — page updated in-place
            await page.wait_for_timeout(3000)
            print("    Page updated (same URL)")

        await page.wait_for_timeout(2000)
        title = await page.title()
        print(f"    Title: {title}")

        ss = Path(__file__).parent / f"booking_step{step + 1}.png"
        await page.screenshot(path=str(ss), full_page=True)
        print(f"    Screenshot: {ss}")

        # After clicking "Complete booking", check if payment section appeared
        if is_complete:
            payment_info = await _detect_payment_step(page)
            if payment_info.get("saved_card") or payment_info.get("is_payment_step"):
                result["payment_info"] = payment_info
                break

            # Check if confirmed (no payment needed — rare)
            body_text = await page.evaluate(
                "() => (document.body.innerText || '').substring(0, 500)"
            )
            if re.search(r"confirmed|congratulations|thank you", body_text, re.I):
                result["status"] = "CONFIRMED"
                result["is_confirmed"] = True
                break

        # Check if stuck (still on same step)
        if step > 0 and "your details" in title.lower():
            print("    Still on 'Your Details' — checking for validation errors")
            errors = await page.evaluate("""
            () => {
                const errs = document.querySelectorAll(
                    '.bui-form__error, [role="alert"], .field-error'
                );
                return Array.from(errs).map(e => e.textContent.trim()).filter(t => t);
            }
            """)
            if errors:
                print(f"    Errors: {errors[:3]}")
            break

    # Final payment detection
    if "payment_info" not in result:
        payment_info = await _detect_payment_step(page)
        result["payment_info"] = payment_info

    payment_info = result.get("payment_info", {})
    print(f"\n  Payment step: {payment_info.get('is_payment_step')}")
    print(f"  Saved card: {payment_info.get('saved_card', 'none')}")
    print(f"  Needs CVV: {payment_info.get('needs_cvv')}")
    print(f"  Total: {payment_info.get('total_price', '?')}")

    if payment_info.get("saved_card"):
        result["status"] = "SAVED_CARD_AVAILABLE"
        result["saved_card"] = payment_info["saved_card"]
        print(f"\n  SAVED CARD FOUND: {payment_info['saved_card']}")
    elif result.get("status") != "CONFIRMED":
        result["status"] = "NEEDS_CARD"
        print("\n  NO SAVED CARD — manual card entry required")

    result["page_url"] = page.url
    result["page_title"] = await page.title()
    snippet = await page.evaluate(
        "() => (document.body.innerText || '').substring(0, 1000)"
    )
    result["page_text_snippet"] = snippet

    return result


async def _cancel_booking(page, context, confirmation: dict) -> dict:
    """Cancel a confirmed booking."""
    print(f"\n{'='*60}")
    print("  CANCELLING BOOKING...")
    print(f"{'='*60}\n")

    result = {"cancel_status": "PENDING"}

    # Try cancel URL from confirmation page
    cancel_url = confirmation.get("cancel_url", "")

    if not cancel_url:
        # Try finding cancel link on current page
        cancel_link = page.locator(
            'a[href*="cancel"], a:has-text("Cancel your booking"), '
            'a:has-text("Cancel booking"), '
            'a:has-text("Manage your booking")'
        ).first
        if await cancel_link.is_visible(timeout=3000):
            cancel_url = await cancel_link.get_attribute("href")

    if not cancel_url:
        # Go to manage bookings page
        cancel_url = "https://secure.booking.com/mybooking.html"
        print(f"  No cancel link found, going to: {cancel_url}")

    # Navigate to cancel page
    cancel_page = page
    if cancel_url and cancel_url != page.url:
        if cancel_url.startswith("http"):
            cancel_page = await context.new_page()
            await cancel_page.goto(cancel_url, wait_until="domcontentloaded")
        else:
            await page.goto(cancel_url, wait_until="domcontentloaded")
        await cancel_page.wait_for_timeout(3000)

    print(f"  On page: {cancel_page.url[:100]}")

    # Look for cancel button
    cancel_btn = cancel_page.locator(
        'button:has-text("Cancel booking"), '
        'button:has-text("Cancel your booking"), '
        'a:has-text("Cancel booking"), '
        'a:has-text("Cancel your booking"), '
        'button:has-text("Cancel reservation"), '
        '[data-testid="cancel-booking-button"]'
    ).first

    if await cancel_btn.is_visible(timeout=5000):
        print("  Found cancel button, clicking...")
        await cancel_btn.click()
        await cancel_page.wait_for_timeout(3000)

        # Handle confirmation dialog / reason selection
        # Some sites ask for a reason
        reason_select = cancel_page.locator(
            'select[name*="reason"], '
            'input[type="radio"][name*="reason"]'
        ).first
        if await reason_select.is_visible(timeout=2000):
            print("  Selecting cancellation reason...")
            try:
                await reason_select.select_option(index=0)
            except Exception:
                await reason_select.click()
            await cancel_page.wait_for_timeout(500)

        # Confirm cancellation
        confirm_cancel = cancel_page.locator(
            'button:has-text("Cancel booking"), '
            'button:has-text("Yes, cancel"), '
            'button:has-text("Confirm cancellation"), '
            'button:has-text("Cancel my booking"), '
            '[data-testid="confirm-cancel-button"]'
        ).first

        if await confirm_cancel.is_visible(timeout=3000):
            print("  Confirming cancellation...")
            await confirm_cancel.click()
            await cancel_page.wait_for_timeout(5000)

        # Check if cancelled
        page_text = await cancel_page.evaluate(
            "() => document.body.innerText"
        )
        is_cancelled = bool(
            re.search(r"cancel+ed|cancel+ation.*confirm", page_text, re.I)
        )

        ss = Path(__file__).parent / "booking_cancelled.png"
        await cancel_page.screenshot(path=str(ss), full_page=True)
        print(f"  Screenshot: {ss}")

        if is_cancelled:
            result["cancel_status"] = "CANCELLED"
            print("\n  BOOKING CANCELLED SUCCESSFULLY!")
        else:
            result["cancel_status"] = "UNCLEAR"
            print("\n  Cancellation status unclear")
            print(f"  Page: {cancel_page.url[:100]}")
    else:
        print("  Cancel button not found on page")
        ss = Path(__file__).parent / "booking_cancel_page.png"
        await cancel_page.screenshot(path=str(ss), full_page=True)
        print(f"  Screenshot: {ss}")
        result["cancel_status"] = "BUTTON_NOT_FOUND"

    if cancel_page != page:
        await cancel_page.close()

    return result


# ── Payment Detection & Card Handling ────────────────────────────────────────


async def _detect_payment_step(page) -> dict:
    """Detect if we're on the payment step and check for saved cards."""
    js = r"""
    () => {
        const text = document.body.innerText || '';
        const html = document.body.innerHTML || '';

        // Detect payment step
        const isPaymentStep = (
            /credit card|debit card|payment (method|detail|info)|card number/i.test(text)
            || /how.*(?:you like to|want to).*pay/i.test(text)
            || !!document.querySelector(
                'input[name*="cc_number"], input[name*="card_number"], '
                + 'input[autocomplete="cc-number"], '
                + '[data-testid="payment-method"], '
                + '.payment-method, #payment'
            )
        );

        // Detect saved card — multiple approaches
        // 1. Text regex: "Visa ••1732", "Visa ****1732", "Mastercard ending in 4242"
        const savedCardMatch = text.match(
            /(Visa|Mastercard|Amex|American Express|Discover|Maestro|JCB)[^\d]{0,30}?(\d{4})/i
        );
        let savedCard = savedCardMatch
            ? `${savedCardMatch[1]} ••••${savedCardMatch[2]}`
            : '';

        // 2. DOM approach: look for card-related elements
        if (!savedCard) {
            // booking.com uses elements like "Your Saved Card" section
            const cardEls = document.querySelectorAll(
                '[data-testid*="card"], [class*="saved-card"], '
                + '[class*="payment-card"], [class*="PaymentCard"], '
                + '[class*="credit-card"], [class*="CreditCard"]'
            );
            for (const el of cardEls) {
                const ct = el.textContent || '';
                const m = ct.match(/(Visa|Mastercard|Amex|Maestro|JCB)[^\d]{0,30}?(\d{4})/i);
                if (m) {
                    savedCard = `${m[1]} ••••${m[2]}`;
                    break;
                }
            }
        }

        // 3. Look for any element mentioning saved card
        if (!savedCard) {
            const allEls = document.querySelectorAll('span, div, label, p');
            for (const el of allEls) {
                const ct = el.textContent || '';
                if (ct.length < 100) {
                    const m = ct.match(/(Visa|Mastercard|Amex|Maestro|JCB)[^\d]{0,20}?(\d{4})/i);
                    if (m) {
                        savedCard = `${m[1]} ••••${m[2]}`;
                        break;
                    }
                }
            }
        }

        // Check if saved card is selected (radio/checkbox checked)
        const savedCardSelected = !!document.querySelector(
            'input[type="radio"][name*="payment"][checked], '
            + 'input[type="radio"][name*="card"][checked], '
            + '.payment-method--selected, '
            + '[data-testid="saved-card-selected"]'
        );

        // Check if CVV field is visible
        const needsCvv = !!document.querySelector(
            'input[name*="cvc"], input[name*="cvv"], '
            + 'input[autocomplete="cc-csc"], '
            + 'input[placeholder*="CVV"], input[placeholder*="CVC"], '
            + 'input[placeholder*="Security code"]'
        );
        const cvvField = document.querySelector(
            'input[name*="cvc"], input[name*="cvv"], '
            + 'input[autocomplete="cc-csc"]'
        );
        const cvvVisible = cvvField
            ? cvvField.offsetParent !== null
            : false;

        // Total price
        const priceEl = document.querySelector(
            '[data-testid="total-price"], '
            + '.bui-price-display__value, '
            + '.bp-price-details__total-amount, '
            + '.priceIsland__total-price'
        );

        // "Complete booking" or "Book now" button
        const completeBtn = Array.from(document.querySelectorAll('button, input[type="submit"]'))
            .find(b => /complete.*book|book\s*now|finish.*book|confirm.*book/i.test(
                b.textContent || b.value || ''
            ));

        return {
            is_payment_step: isPaymentStep,
            saved_card: savedCard,
            saved_card_selected: savedCardSelected,
            needs_cvv: needsCvv,
            cvv_visible: cvvVisible,
            total_price: priceEl ? priceEl.textContent.trim() : '',
            has_complete_button: !!completeBtn,
            complete_button_text: completeBtn
                ? (completeBtn.textContent || completeBtn.value).trim() : '',
            page_title: document.title,
            page_url: window.location.href,
        };
    }
    """
    result = await page.evaluate(js)

    # Check inside payment iframe (booking.com uses paymentcomponent.booking.com)
    if not result.get("saved_card"):
        for frame in page.frames:
            if "paymentcomponent" in frame.url or "payment" in frame.url:
                try:
                    iframe_info = await frame.evaluate(r"""
                    () => {
                        const text = document.body.innerText || '';
                        const html = document.body.innerHTML || '';

                        // Look for saved card text
                        const cardMatch = text.match(
                            /(Visa|Mastercard|Amex|Maestro|JCB)[^\d]{0,30}?(\d{4})/i
                        );

                        // Look for card number in inputs/labels
                        let cardFromDom = '';
                        document.querySelectorAll('span, div, label, p, li').forEach(el => {
                            const ct = el.textContent || '';
                            if (ct.length < 80) {
                                const m = ct.match(
                                    /(Visa|Mastercard|Amex|Maestro|JCB)[^\d]{0,20}?(\d{4})/i
                                );
                                if (m && !cardFromDom) {
                                    cardFromDom = `${m[1]} ••••${m[2]}`;
                                }
                            }
                        });

                        // Check for "Saved Card" text
                        const hasSavedCard = /saved card|your card|stored card/i.test(text);

                        // CVV field in iframe
                        const hasCvv = !!document.querySelector(
                            'input[name*="cvc"], input[name*="cvv"], '
                            + 'input[autocomplete="cc-csc"], '
                            + 'input[placeholder*="CVV"], input[placeholder*="CVC"]'
                        );

                        return {
                            saved_card: cardMatch
                                ? `${cardMatch[1]} ••••${cardMatch[2]}`
                                : cardFromDom,
                            has_saved_card_text: hasSavedCard,
                            has_cvv: hasCvv,
                            text_snippet: text.substring(0, 500),
                        };
                    }
                    """)
                    if iframe_info.get("saved_card"):
                        result["saved_card"] = iframe_info["saved_card"]
                        result["needs_cvv"] = iframe_info.get("has_cvv", False)
                    elif iframe_info.get("has_saved_card_text"):
                        result["saved_card"] = "saved card detected (details in iframe)"
                    # Store iframe text for debugging
                    result["iframe_text"] = iframe_info.get("text_snippet", "")
                except Exception as e:
                    result["iframe_error"] = str(e)
                break

    return result


async def _complete_with_saved_card(page) -> dict:
    """Complete booking using a saved card on booking.com.

    Booking.com flow:
    1. Click "Complete booking" → payment options expand (saved card shown)
    2. Ensure saved card is selected
    3. Click "Complete booking" again → booking confirmed
    """
    print(f"\n{'='*60}")
    print("  COMPLETING WITH SAVED CARD...")
    print(f"{'='*60}\n")

    result = {"is_confirmed": False}

    for attempt in range(3):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000)

        complete_btn = page.locator(
            'button:has-text("Complete booking"), '
            'button:has-text("Complete Booking"), '
            'button:has-text("Book now"), '
            'button:has-text("Finish booking")'
        ).first

        if not await complete_btn.is_visible(timeout=5000):
            print(f"  Attempt {attempt + 1}: No 'Complete booking' button")
            break

        btn_text = (await complete_btn.text_content()).strip()
        print(f"  Attempt {attempt + 1}: Clicking '{btn_text}'...")

        try:
            async with page.expect_navigation(
                wait_until="domcontentloaded", timeout=15000
            ):
                await complete_btn.click()
            print(f"  Navigated! URL: {page.url[:80]}")
        except Exception:
            await page.wait_for_timeout(3000)
            print(f"  Page updated. URL: {page.url[:80]}")

        await page.wait_for_timeout(2000)

        ss = Path(__file__).parent / f"booking_complete_{attempt + 1}.png"
        await page.screenshot(path=str(ss), full_page=True)
        print(f"  Screenshot: {ss}")

        # Check if a payment method selection appeared
        # On booking.com, clicking "Complete" first time shows card selection
        saved_card_el = page.locator(
            '[data-testid="saved-card"], '
            'text=/Your Saved Card/i, '
            'text=/Visa.*\\d{4}/i, '
            'text=/Mastercard.*\\d{4}/i'
        ).first

        if await saved_card_el.is_visible(timeout=2000):
            print("  Payment section visible — selecting saved card...")

            # Click on saved card to ensure it's selected
            card_option = page.locator(
                'label:has-text("Visa"), '
                'label:has-text("Mastercard"), '
                'input[type="radio"][value*="saved"], '
                '[data-testid="saved-card"] input'
            ).first
            if await card_option.is_visible(timeout=2000):
                await card_option.click()
                await page.wait_for_timeout(500)
                print("  Saved card selected")

            # Check if CVV is required
            cvv_field = page.locator(
                'input[name*="cvc"], input[name*="cvv"], '
                'input[autocomplete="cc-csc"]'
            ).first
            if await cvv_field.is_visible(timeout=2000):
                print("  CVV REQUIRED — cannot auto-complete")
                result["needs_cvv"] = True
                result["page_url"] = page.url
                return result

            continue  # Click "Complete booking" again

        # Check for confirmation
        body_text = await page.evaluate("() => document.body.innerText")
        is_confirmed = bool(
            re.search(
                r"confirmed|congratulations|thank you for.*book|"
                r"booking.*complete|your trip",
                body_text, re.I,
            )
        )

        if is_confirmed:
            conf_match = re.search(
                r"confirmation.*?([A-Z0-9][\w\-\.]{3,})", body_text, re.I
            ) or re.search(
                r"(?:ref|PIN)[:\s#]*([0-9]{4,})", body_text, re.I
            )
            result["is_confirmed"] = True
            result["confirmation_number"] = conf_match.group(1) if conf_match else ""
            result["page_url"] = page.url

            # Find cancel link
            cancel_url = await page.evaluate(r"""
            () => {
                const a = Array.from(document.querySelectorAll('a'))
                    .find(a => /cancel|manage.*book|mybooking/i.test(
                        (a.textContent || '') + (a.href || '')
                    ));
                return a ? a.href : '';
            }
            """)
            result["cancel_url"] = cancel_url
            print(f"  CONFIRMED! #{result.get('confirmation_number', '?')}")
            break

        # Check for errors
        errors = await page.evaluate("""
        () => {
            const errs = document.querySelectorAll(
                '.bui-form__error, [role="alert"], .field-error, '
                + '.validation-error, .bp-form__error, .error-message'
            );
            return Array.from(errs).map(e => e.textContent.trim()).filter(t => t);
        }
        """)
        if errors:
            print(f"  Errors: {errors[:3]}")
            result["errors"] = errors[:3]
            break

    if not result.get("is_confirmed"):
        title = await page.title()
        snippet = await page.evaluate(
            "() => (document.body.innerText || '').substring(0, 300)"
        )
        print(f"  Not confirmed. Title: {title}")
        print(f"  Snippet: {snippet[:200]}")
        result["page_url"] = page.url

    ss = Path(__file__).parent / "booking_confirmation.png"
    await page.screenshot(path=str(ss), full_page=True)
    print(f"  Final screenshot: {ss}")

    return result


async def _do_cancel_flow(page, context):
    """Cancel a confirmed booking from the confirmation page."""
    print(f"\n{'='*60}")
    print("  CANCELLING BOOKING...")
    print(f"{'='*60}\n")

    # Look for cancel/manage link on confirmation page
    cancel_link = page.locator(
        'a:has-text("Cancel"), '
        'a:has-text("Manage"), '
        'a[href*="cancel"], '
        'a[href*="mybooking"]'
    ).first

    if await cancel_link.is_visible(timeout=5000):
        await cancel_link.click()
        await page.wait_for_timeout(5000)
    else:
        await page.goto(
            "https://secure.booking.com/mybooking.html",
            wait_until="domcontentloaded",
        )
        await page.wait_for_timeout(3000)

    print(f"  On: {page.url[:100]}")

    # Click cancel booking
    cancel_btn = page.locator(
        'button:has-text("Cancel booking"), '
        'button:has-text("Cancel your booking"), '
        'a:has-text("Cancel booking"), '
        'a:has-text("Cancel your booking")'
    ).first

    if await cancel_btn.is_visible(timeout=5000):
        await cancel_btn.click()
        await page.wait_for_timeout(3000)

        # Select reason if asked
        reason = page.locator(
            'select[name*="reason"], input[type="radio"][name*="reason"]'
        ).first
        if await reason.is_visible(timeout=2000):
            try:
                await reason.select_option(index=0)
            except Exception:
                await reason.click()
            await page.wait_for_timeout(500)

        # Confirm cancellation
        confirm_btn = page.locator(
            'button:has-text("Cancel booking"), '
            'button:has-text("Yes, cancel"), '
            'button:has-text("Confirm")'
        ).first
        if await confirm_btn.is_visible(timeout=3000):
            await confirm_btn.click()
            await page.wait_for_timeout(5000)

        ss = Path(__file__).parent / "booking_cancelled.png"
        await page.screenshot(path=str(ss), full_page=True)

        cancel_text = await page.evaluate("() => document.body.innerText")
        if re.search(r"cancel+ed|cancel+ation", cancel_text, re.I):
            print("  BOOKING CANCELLED!")
        else:
            print("  Cancellation status unclear")
            print(f"  Page: {page.url[:80]}")
    else:
        print("  Cancel button not found")
        ss = Path(__file__).parent / "booking_cancel_page.png"
        await page.screenshot(path=str(ss), full_page=True)


# ── Main ─────────────────────────────────────────────────────────────────────


async def do_full_flow():
    """Login → Search → Book → Complete → Cancel in ONE browser session."""
    from playwright.async_api import async_playwright

    city = get_arg("city", "Barcelona")
    checkin = get_arg("checkin", "2026-03-15")
    checkout = get_arg("checkout", "2026-03-18")
    adults = int(get_arg("adults", "2"))
    children = int(get_arg("children", "0"))
    child_ages_str = get_arg("child-ages", "")
    child_ages = (
        [int(a) for a in child_ages_str.split(",") if a.strip()]
        if child_ages_str else []
    )
    rooms = int(get_arg("rooms", "1"))
    sort_by = get_arg("sort")
    free_cancel = "--free-cancel" in sys.argv
    book_index = get_arg("book")

    print(f"\n{'='*60}")
    print("  FULL FLOW: Login → Search → Book → Complete → Cancel")
    print(f"  {city} | {checkin} → {checkout}")
    print(f"  {adults} adults, {children} children")
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

        # ── 1. LOGIN ──
        print("  [STEP 1] Opening booking.com login...")
        page = await context.new_page()
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")

        print("  Log in manually. Waiting up to 3 min...\n")
        for attempt in range(60):
            await asyncio.sleep(3)
            current_url = page.url
            left_signin = (
                "sign-in" not in current_url
                and "signin" not in current_url
                and "login" not in current_url
            )
            if left_signin:
                print(f"  Login OK! Page: {current_url[:60]}")
                break
            if attempt % 10 == 0:
                print(f"  [{attempt * 3}s] waiting for login...")
        else:
            print("  Timeout — proceeding anyway")

        try:
            await page.wait_for_timeout(2000)
        except Exception:
            print("  Browser was closed during login wait")
            return

        # Save cookies
        storage = await context.storage_state()
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump(storage, f, indent=2, ensure_ascii=False)
        bk = [c for c in storage["cookies"] if "booking" in c.get("domain", "")]
        print(f"  Saved {len(bk)} booking cookies")

        # ── 2. SEARCH ──
        print(f"\n  [STEP 2] Searching hotels in {city}...")
        search_url = _build_search_url(
            city, checkin, checkout, adults, children, child_ages, rooms,
            sort_by=sort_by, free_cancel=free_cancel,
        )
        await page.goto(search_url, wait_until="domcontentloaded")
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
            except Exception:
                pass

        try:
            await page.wait_for_selector(
                '[data-testid="property-card"]', timeout=15000
            )
        except Exception:
            await page.wait_for_timeout(5000)

        hotels = await _extract_hotels(page)
        if not hotels:
            print("  No hotels found!")
            await browser.close()
            return

        print(f"\n  FOUND {len(hotels)} HOTELS:")
        for i, h in enumerate(hotels, 1):
            print(f"  {i}. {h['name']} — {h['price']} "
                  f"({h['rating']}/10, {h['distance']})")

        if not book_index:
            book_index = "1"

        idx = int(book_index) - 1
        if idx < 0 or idx >= len(hotels):
            print(f"  Invalid index: {book_index}")
            await browser.close()
            return

        hotel = hotels[idx]

        # ── 3. BOOK — open hotel page, select room ──
        print(f"\n  [STEP 3] Booking: {hotel['name']}...")
        hotel_url = hotel.get("url", "")
        if not hotel_url:
            print("  No hotel URL!")
            await browser.close()
            return

        await page.goto(hotel_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Select room
        room_selects = page.locator('select.hprt-nos-select')
        if await room_selects.count() > 0:
            first_select = room_selects.first
            await first_select.scroll_into_view_if_needed()
            await page.wait_for_timeout(500)
            await first_select.select_option("1")
            await page.wait_for_timeout(1000)
            print("  Selected 1 room")
        else:
            print("  No room dropdown found")

        # Click I'll reserve
        reserve_btn = page.locator(
            'button.js-reservation-button, '
            'button:has-text("I\'ll reserve"), '
            'button:has-text("Reserve")'
        ).first

        if await reserve_btn.is_visible(timeout=5000):
            try:
                async with page.expect_navigation(
                    wait_until="domcontentloaded", timeout=15000
                ):
                    await reserve_btn.click()
                print(f"  On booking form: {page.url[:80]}")
            except Exception:
                # Navigation may still be in progress
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                await page.wait_for_timeout(3000)
                print(f"  After click: {page.url[:80]}")

        # Wait for page to be fully loaded
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)

        try:
            title = await page.title()
            print(f"  Page: {title}")
        except Exception:
            await page.wait_for_timeout(3000)
            title = await page.title()
            print(f"  Page (retry): {title}")

        ss = Path(__file__).parent / "booking_screenshot.png"
        await page.screenshot(path=str(ss), full_page=True)

        # Check booking form state and fill if needed
        js_check = """
        () => {
            const text = document.body.innerText || '';
            const hasPayment = /credit card|payment details|card number/i.test(text);
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
                has_payment: hasPayment,
                has_form: !!firstName,
                first: firstName ? firstName.value : '',
                last: lastName ? lastName.value : '',
                email: email ? email.value : '',
                snippet: text.substring(0, 500),
            };
        }
        """
        form_state = await page.evaluate(js_check)
        print(f"  Form state: first='{form_state.get('first')}', "
              f"last='{form_state.get('last')}', "
              f"email='{form_state.get('email')}'")
        print(f"  Has payment form: {form_state.get('has_payment')}")

        # Fill form if empty
        if form_state.get("has_form") and not form_state.get("first"):
            print("  Filling empty form fields...")
            await _fill_booking_form(page, {})
            await page.wait_for_timeout(1000)

        # ── 4. ADVANCE through booking form steps ──
        print("\n  [STEP 4] Advancing through booking steps...")

        for step in range(5):
            await page.evaluate(
                "window.scrollTo(0, document.body.scrollHeight)"
            )
            await page.wait_for_timeout(1000)

            # Check if we've reached the payment/final step
            payment_info = await _detect_payment_step(page)
            if payment_info.get("is_payment_step"):
                print("  Reached payment step!")
                break

            next_btn = page.locator(
                'button:has-text("Next: Final details"), '
                'button:has-text("Final details")'
            ).first

            if not await next_btn.is_visible(timeout=3000):
                print(f"  Step {step + 1}: No 'Next' button — may be on final step")
                break

            btn_text = (await next_btn.text_content()).strip()
            print(f"  Step {step + 1}: Clicking '{btn_text}'...")
            try:
                async with page.expect_navigation(
                    wait_until="domcontentloaded", timeout=15000
                ):
                    await next_btn.click()
            except Exception:
                await page.wait_for_timeout(3000)

            await page.wait_for_timeout(2000)
            ss = Path(__file__).parent / f"booking_step{step + 1}.png"
            await page.screenshot(path=str(ss), full_page=True)
            print(f"    Screenshot: {ss}")
            print(f"    Title: {await page.title()}")

            # Check if stuck on same page (validation errors)
            curr_title = await page.title()
            if "your details" in curr_title.lower() and step > 0:
                print("    Stuck on 'Your Details' — filling missing fields")
                await _fill_booking_form(page, {})
                await page.wait_for_timeout(500)

        # ── 5. DETECT SAVED CARD / PAYMENT ──
        print("\n  [STEP 5] Checking payment options...")
        payment_info = await _detect_payment_step(page)

        ss = Path(__file__).parent / "booking_payment.png"
        await page.screenshot(path=str(ss), full_page=True)
        print(f"  Screenshot: {ss}")

        print(f"  Is payment step: {payment_info.get('is_payment_step')}")
        print(f"  Saved card: {payment_info.get('saved_card', 'none')}")
        print(f"  Needs CVV: {payment_info.get('needs_cvv')}")
        print(f"  Total: {payment_info.get('total_price', 'unknown')}")

        booking_url = page.url

        if payment_info.get("saved_card"):
            card_info = payment_info["saved_card"]
            print(f"\n  SAVED CARD FOUND: {card_info}")

            if "--use-saved-card" in sys.argv:
                # User explicitly wants to use saved card
                print("  Using saved card to complete booking...")
                confirmation = await _complete_with_saved_card(page)

                if confirmation.get("is_confirmed"):
                    print("\n  BOOKING CONFIRMED!")
                    conf_num = confirmation.get("confirmation_number", "")
                    if conf_num:
                        print(f"  Confirmation #: {conf_num}")

                    # Cancel if requested
                    if "--cancel-booking" in sys.argv:
                        await _do_cancel_flow(page, context)
                else:
                    print("\n  Booking not confirmed (may need CVV)")
                    print(f"  Complete manually: {booking_url}")
            else:
                print("\n  To auto-complete with saved card: --use-saved-card")
                print(f"  Or complete manually: {booking_url}")
        else:
            print("\n  NO SAVED CARD — user must enter card details")
            print(f"  Booking URL: {booking_url}")

        # ── Done ──
        result = {
            "hotel": hotel,
            "status": "SAVED_CARD" if payment_info.get("saved_card")
                      else "NEEDS_CARD",
            "saved_card": payment_info.get("saved_card", ""),
            "needs_cvv": payment_info.get("needs_cvv", False),
            "total_price": payment_info.get("total_price", ""),
            "booking_url": booking_url,
            "final_url": page.url,
        }
        with open(RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\n  Result saved to {RESULT_FILE}")

        # Keep browser open for manual action if not auto-completing
        if not payment_info.get("saved_card") or "--use-saved-card" not in sys.argv:
            print("\n  Browser stays open for 60s for manual action...")
            print("  Press Ctrl+C to close early")
            try:
                await page.wait_for_timeout(60000)
            except Exception:
                pass

        await browser.close()


async def main():
    if "--full" in sys.argv:
        await do_full_flow()
    elif "--search" in sys.argv:
        await do_search()
    else:
        await do_login()
        print("\n  Now run with --search or --full")


if __name__ == "__main__":
    asyncio.run(main())
