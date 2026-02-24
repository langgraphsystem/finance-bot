"""Launch Chrome for manual login, auto-detect when done, save cookies.

Usage: python scripts/test_browser_login.py [--search]
  No args     → launch Chrome, wait for login, save cookies
  --search    → skip login, run hotel search with saved cookies
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

COOKIES_FILE = Path(__file__).parent / "booking_cookies.json"
RESULT_FILE = Path(__file__).parent / "search_result.json"
LOGIN_URL = "https://account.booking.com/sign-in"
SITE = "booking.com"


async def launch_and_wait_for_login():
    """Launch visible Chrome, auto-detect login via cookies, save state."""
    from playwright.async_api import async_playwright

    print(f"\n{'='*60}")
    print(f"  Launching Chrome → {LOGIN_URL}")
    print(f"  Log in manually — I'll detect it automatically.")
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
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")

        print("  Waiting for booking.com login...")
        print("  (checking cookies every 3 seconds)\n")

        # Poll for session cookies indicating successful login
        for attempt in range(40):  # 2 minutes max
            await asyncio.sleep(3)
            cookies = await context.cookies("https://www.booking.com")
            booking_cookies = {c["name"]: c["value"] for c in cookies}

            # Check for REAL auth tokens (not empty sessions like "e30" = "{}")
            auth_token = booking_cookies.get("bkng_sso_auth", "")
            login_token = booking_cookies.get("logintoken", "")
            pcm = booking_cookies.get("pcm_personalization", "")

            # bkng_sso_auth with real content (not empty) = logged in
            has_real_auth = len(auth_token) > 20
            has_login_token = bool(login_token)
            has_personalization = bool(pcm)

            is_logged_in = has_real_auth and (has_login_token or has_personalization)

            if is_logged_in:
                print(f"  Login detected! ({len(cookies)} cookies)")
                print(f"    bkng_sso_auth: {auth_token[:30]}...")
                if login_token:
                    print(f"    logintoken: {login_token[:30]}...")
                break

            if attempt % 10 == 0:
                status = "waiting for login..."
                if has_real_auth:
                    status = "have auth token, waiting for login/pcm cookies..."
                print(f"  [{attempt * 3}s] {status} ({len(cookies)} cookies)")
        else:
            print("  Timeout waiting for login. Saving whatever we have.")

        # Give a moment for all cookies to settle
        await asyncio.sleep(2)

        # Save storage state
        storage_state = await context.storage_state()
        cookie_count = len(storage_state.get("cookies", []))

        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump(storage_state, f, indent=2, ensure_ascii=False)

        booking_cookies = [
            c for c in storage_state["cookies"]
            if "booking" in c.get("domain", "")
        ]
        print(f"\n  Saved {cookie_count} total cookies ({len(booking_cookies)} booking.com)")
        print(f"  File: {COOKIES_FILE}")

        for c in booking_cookies[:8]:
            val_preview = c["value"][:25] + "..." if len(c["value"]) > 25 else c["value"]
            print(f"    {c['name']}: {val_preview}")

        await browser.close()

    return COOKIES_FILE


async def test_browser_search():
    """Run browser-use hotel search with saved cookies.

    Supports CLI args:
      --search                  Run search (required)
      --city Barcelona          Destination (default: Barcelona)
      --checkin 2026-03-15      Check-in date
      --checkout 2026-03-18     Check-out date
      --adults 2                Number of adults (default: 2)
      --children 1              Number of children (default: 0)
      --child-ages 5,8          Ages of children (comma-separated)
      --rooms 1                 Number of rooms (default: 1)
      --max-price 150           Max price per night filter
      --sort price              Sort: price, rating, distance, best
      --stars 4                 Minimum star rating filter
      --free-cancel             Only show free cancellation
      --breakfast               Only show breakfast included
      --pool                    Only show hotels with pool
      --book 2                  Book hotel #N from results
    """
    import re

    import os
    import tempfile

    from browser_use import Agent as BrowserAgent
    from browser_use import BrowserProfile
    from browser_use import ChatAnthropic

    if not COOKIES_FILE.exists():
        print("  No cookies file found. Run without --search first.")
        return

    # Parse CLI args
    args = sys.argv[1:]
    def get_arg(name, default=None):
        try:
            idx = args.index(f"--{name}")
            return args[idx + 1] if idx + 1 < len(args) else default
        except ValueError:
            return default

    city = get_arg("city", "Barcelona")
    checkin = get_arg("checkin", "2026-03-15")
    checkout = get_arg("checkout", "2026-03-18")
    adults = int(get_arg("adults", "2"))
    children = int(get_arg("children", "0"))
    child_ages_str = get_arg("child-ages", "")
    child_ages = [int(a) for a in child_ages_str.split(",") if a.strip()] if child_ages_str else []
    rooms = int(get_arg("rooms", "1"))
    max_price = get_arg("max-price")
    sort_by = get_arg("sort")
    stars = get_arg("stars")
    free_cancel = "--free-cancel" in args
    breakfast = "--breakfast" in args
    pool = "--pool" in args
    book_index = get_arg("book")

    print(f"\n{'='*60}")
    print(f"  Hotel search: {city}")
    print(f"  Dates: {checkin} → {checkout}")
    print(f"  Guests: {adults} adults, {children} children, {rooms} room(s)")
    if child_ages:
        print(f"  Child ages: {child_ages}")
    if max_price:
        print(f"  Max price: ${max_price}/night")
    if sort_by:
        print(f"  Sort: {sort_by}")
    if stars:
        print(f"  Min stars: {stars}")
    filters_list = []
    if free_cancel:
        filters_list.append("free cancellation")
    if breakfast:
        filters_list.append("breakfast included")
    if pool:
        filters_list.append("pool")
    if filters_list:
        print(f"  Filters: {', '.join(filters_list)}")
    print(f"{'='*60}\n")

    with open(COOKIES_FILE, encoding="utf-8") as f:
        storage_state = json.load(f)

    print(f"  Loaded {len(storage_state.get('cookies', []))} cookies")

    # Ensure config dir exists (browser-use requirement)
    if not os.getenv("BROWSER_USE_CONFIG_DIR"):
        cfg_dir = os.path.join(tempfile.gettempdir(), "browseruse")
        os.makedirs(cfg_dir, exist_ok=True)
        os.environ["BROWSER_USE_CONFIG_DIR"] = cfg_dir

    # WORKAROUND: browser-use StorageStateWatchdog bug on Windows —
    # it uses storage_state dict as a filename. Save to temp file instead.
    state_file = os.path.join(tempfile.gettempdir(), "bu_storage_state.json")
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(storage_state, f)
    print(f"  Storage state file: {state_file}")

    # Build guest section
    guest_section = f"{adults} adults"
    if children > 0:
        guest_section += f", {children} {'child' if children == 1 else 'children'}"
        if child_ages:
            guest_section += f" (ages: {', '.join(str(a) for a in child_ages)})"
    guest_section += f", {rooms} room{'s' if rooms > 1 else ''}"

    # Build children steps
    children_steps = ""
    if children > 0:
        children_steps = (
            f"4b. Click the guests/occupancy field\n"
            f"4c. Set adults to {adults}\n"
            f"4d. Set children to {children}\n"
        )
        for i, age in enumerate(child_ages):
            children_steps += (
                f"4{chr(101+i)}. Set child {i+1} age to {age}\n"
            )
        children_steps += "4z. Click Done/Apply\n"

    # Build filter steps
    filter_steps = ""
    if max_price:
        filter_steps += (
            f"6a. Set price filter: max ${max_price} per night "
            f"(look for price slider or 'Your budget' filter on the left sidebar)\n"
        )
    if stars:
        filter_steps += (
            f"6b. Apply star rating filter: {stars}+ stars "
            f"(look for 'Property rating' or star checkboxes in filters)\n"
        )
    if free_cancel:
        filter_steps += (
            "6c. Check 'Free cancellation' filter in the left sidebar\n"
        )
    if breakfast:
        filter_steps += (
            "6d. Check 'Breakfast included' filter (under 'Meals' in sidebar)\n"
        )
    if pool:
        filter_steps += (
            "6e. Check 'Swimming pool' filter (under 'Facilities' in sidebar)\n"
        )

    # Build sort step
    sort_step = ""
    sort_map = {
        "price": "Price (lowest first)",
        "rating": "Top reviewed",
        "distance": "Distance from city center",
        "best": "Our top picks",
    }
    if sort_by and sort_by in sort_map:
        sort_step = (
            f"6f. Click the sort dropdown at the top of results and select "
            f"'{sort_map[sort_by]}'\n"
        )

    # JS extraction — comprehensive booking.com selectors
    js_extract = (
        "JSON.stringify(Array.from("
        "document.querySelectorAll('[data-testid=\"property-card\"]')"
        ").slice(0,5).map(c=>({name:c.querySelector('[data-testid=\"title\"]')"
        "?.textContent?.trim()||'',"
        "price:c.querySelector('[data-testid=\"price-and-discounted-price\"]')"
        "?.textContent?.trim()||'',"
        "rating:c.querySelector('[data-testid=\"review-score\"]')"
        "?.textContent?.trim()||'',"
        "distance:c.querySelector('[data-testid=\"distance\"]')"
        "?.textContent?.trim()||'',"
        "room_type:c.querySelector('[data-testid=\"recommended-units\"]')"
        "?.textContent?.trim()||'',"
        "cancellation:(c.innerText.match("
        "/free cancellation|no prepayment/i)||[''])[0],"
        "breakfast:(c.innerText.match("
        "/breakfast included|breakfast \\$/i)||[''])[0]"
        "})))"
    )

    task = f"""\
Go to https://www.booking.com and search for hotels.

DESTINATION: {city}
CHECK-IN: {checkin}
CHECK-OUT: {checkout}
GUESTS: {guest_section}

Steps:
1. Close any popups, overlays, or cookie banners
2. Click the destination/search field, type "{city}", select from dropdown
3. Set check-in date to {checkin} and check-out date to {checkout} \
in the date picker
4. Open the guests/occupancy selector and set: {guest_section}
{children_steps}\
4z. Click Done in the occupancy popup
5. Click the Search button
6. Wait for results to fully load (hotel cards must appear)
{filter_steps}{sort_step}\
7. After all filters applied and results reloaded, extract data \
using JavaScript. Run this in the browser console:

{js_extract}

8. Return the JavaScript output as your final answer (the JSON array).

IMPORTANT:
- Use the JavaScript extraction above — do NOT try to read hotel data visually.
- If the JavaScript returns empty array [], scroll down and try again.
- If a CAPTCHA appears, return "CAPTCHA_DETECTED".
- If login popup appears, close it and continue.
- Stay on the results page. Do NOT click individual hotels.
"""

    llm = ChatAnthropic(model="claude-sonnet-4-6")

    profile = BrowserProfile(
        headless=False,
        user_data_dir=None,
        storage_state=state_file,  # Pass file path, not dict (Windows bug workaround)
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/133.0.0.0 Safari/537.36"
        ),
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )

    agent = BrowserAgent(task=task, llm=llm, browser_profile=profile)

    max_steps = 50 if (filter_steps or children > 0) else 40
    print(f"  Running agent (max {max_steps} steps, 5 min timeout)...")
    print("  Watch the browser window!\n")

    try:
        result = await asyncio.wait_for(
            agent.run(max_steps=max_steps),
            timeout=300,
        )

        final = result.final_result() if hasattr(result, "final_result") else str(result)

        print(f"\n{'='*60}")
        print("  RAW RESULT:")
        print(f"{'='*60}")
        print(final[:3000] if final else "(empty)")

        # Try to parse JSON
        hotels = []
        if final:
            json_match = re.search(r'\[.*\]', final, re.DOTALL)
            if json_match:
                try:
                    hotels = json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

        if hotels:
            print(f"\n{'='*60}")
            print(f"  PARSED {len(hotels)} HOTELS:")
            print(f"{'='*60}")
            for i, h in enumerate(hotels, 1):
                print(f"\n  {i}. {h.get('name', '?')}")
                price = h.get('price', h.get('price_per_night', '?'))
                print(f"     Price: {price}")
                rating = h.get('rating', '?')
                print(f"     Rating: {rating}")
                print(f"     Distance: {h.get('distance', '?')}")
                if h.get("room_type"):
                    print(f"     Room: {h['room_type'][:80]}")
                if h.get("cancellation"):
                    print(f"     Cancel: {h['cancellation']}")
                if h.get("breakfast"):
                    print(f"     Breakfast: {h['breakfast']}")
        else:
            print("\n  Could not parse hotels from result.")

        # Save full result
        with open(RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"raw": final[:5000] if final else "", "hotels": hotels},
                f, indent=2, ensure_ascii=False,
            )
        print(f"\n  Result saved to {RESULT_FILE}")

        # Booking step
        if book_index and hotels:
            idx = int(book_index) - 1
            if 0 <= idx < len(hotels):
                await test_booking(
                    hotels[idx], city, checkin, checkout,
                    guest_section, storage_state
                )
            else:
                print(f"\n  Invalid hotel index: {book_index}")

    except asyncio.TimeoutError:
        print("\n  TIMEOUT after 5 minutes")
    except Exception as e:
        print(f"\n  ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


async def test_booking(hotel, city, checkin, checkout, guests, storage_state):
    """Try to book a specific hotel — stops before payment."""
    import os
    import tempfile

    from browser_use import Agent as BrowserAgent
    from browser_use import BrowserProfile
    from browser_use import ChatAnthropic

    hotel_name = hotel.get("name", "Unknown")

    print(f"\n{'='*60}")
    print(f"  BOOKING: {hotel_name}")
    print(f"  {city} | {checkin} → {checkout} | {guests}")
    print(f"{'='*60}\n")

    if not os.getenv("BROWSER_USE_CONFIG_DIR"):
        cfg_dir = os.path.join(tempfile.gettempdir(), "browseruse")
        os.makedirs(cfg_dir, exist_ok=True)
        os.environ["BROWSER_USE_CONFIG_DIR"] = cfg_dir

    task = f"""\
Book this hotel on https://www.booking.com:

Hotel: {hotel_name}
City: {city}
Check-in: {checkin}
Check-out: {checkout}
Guests: {guests}

Steps:
1. You are on the booking.com search results page.
2. Find and click on "{hotel_name}" in the results.
3. On the hotel page, select the cheapest available room.
4. Click "Reserve" or "I'll reserve" or "Select" button.
5. On the booking form:
   - Check if guest details are pre-filled (logged-in user)
   - Fill in First Name, Last Name, Email if empty
   - Note the total price and cancellation policy
6. STOP before the final payment/confirm button.
7. Take a screenshot and extract booking details.

Return a JSON object:
{{"status": "READY_TO_BOOK" or "PAYMENT_REQUIRED" or "SOLD_OUT",
  "hotel_name": "{hotel_name}",
  "room_type": "room type shown",
  "total_price": "total price shown",
  "price_per_night": "per night if shown",
  "cancellation": "cancellation policy text",
  "payment_type": "pay_at_hotel" or "prepay_required",
  "booking_url": "current page URL",
  "notes": "any important details"}}

IMPORTANT:
- Do NOT click the final "Complete Booking" / pay button!
- If payment card is required to proceed, report PAYMENT_REQUIRED.
- If hotel is sold out, report SOLD_OUT.
"""

    llm = ChatAnthropic(model="claude-sonnet-4-6")

    # Save storage_state to temp file (Windows bug workaround)
    booking_state_file = os.path.join(
        tempfile.gettempdir(), "bu_booking_state.json"
    )
    with open(booking_state_file, "w", encoding="utf-8") as f:
        json.dump(storage_state, f)

    profile = BrowserProfile(
        headless=False,
        user_data_dir=None,
        storage_state=booking_state_file,
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/133.0.0.0 Safari/537.36"
        ),
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
        ],
    )

    agent = BrowserAgent(task=task, llm=llm, browser_profile=profile)

    print("  Running booking agent (max 30 steps, 3 min timeout)...")
    print("  Watch the browser window!\n")

    try:
        result = await asyncio.wait_for(
            agent.run(max_steps=30),
            timeout=180,
        )
        final = result.final_result() if hasattr(result, "final_result") else str(result)

        print(f"\n{'='*60}")
        print("  BOOKING RESULT:")
        print(f"{'='*60}")
        print(final[:3000] if final else "(empty)")

        # Save
        booking_file = Path(__file__).parent / "booking_result.json"
        with open(booking_file, "w", encoding="utf-8") as f:
            json.dump({"raw": final[:5000] if final else "", "hotel": hotel},
                      f, indent=2, ensure_ascii=False)
        print(f"\n  Saved to {booking_file}")

    except asyncio.TimeoutError:
        print("\n  BOOKING TIMEOUT after 3 minutes")
    except Exception as e:
        print(f"\n  BOOKING ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


async def main():
    if "--search" in sys.argv:
        await test_browser_search()
    else:
        await launch_and_wait_for_login()
        print("\n  Now run with --search to test hotel search:")
        print("  python scripts/test_browser_login.py --search")


if __name__ == "__main__":
    asyncio.run(main())
