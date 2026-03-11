"""Hosted browser connect UI for phone and desktop login flows."""

from __future__ import annotations

import base64
import html

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response

from api.browser_extension import get_bot_username
from api.schemas.browser_connect import BrowserConnectActionRequest, BrowserConnectStateResponse
from src.tools import remote_browser_connect

router = APIRouter(prefix="/api/browser-connect", tags=["browser-connect"])
_BLANK_SCREENSHOT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn8k1EAAAAASUVORK5CYII="
)


def _render_connect_page(token: str, provider: str, *, debug: bool = False) -> str:
    safe_token = html.escape(token)
    debug_panel = """
      <section id="debugPanel" class="debug-panel">
        <div class="debug-title">Advanced tools</div>
        <div class="debug-grid">
          <button id="backPage">Back</button>
          <button id="refreshPage">Refresh page</button>
          <button id="reloadScreen">Reload preview</button>
        </div>
      </section>
    """ if debug else ""
    debug_js = """
    document.getElementById('backPage').addEventListener(
      'click',
      () => doAction({ action: 'back' })
    );
    document.getElementById('refreshPage').addEventListener(
      'click',
      () => doAction({ action: 'refresh' })
    );
    document.getElementById('reloadScreen').addEventListener('click', () => reloadAll());
    """ if debug else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Secure Sign In</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f3efe6;
      --panel: rgba(255,255,255,0.92);
      --ink: #18222f;
      --accent: #0f6cbd;
      --accent-2: #d94a1e;
      --line: rgba(24,34,47,0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: "Segoe UI", system-ui, sans-serif;
      background:
        radial-gradient(circle at top left, rgba(217,74,30,0.10), transparent 30%),
        linear-gradient(160deg, #f7f1e7, #d8e4f2 55%, #ebf0d6);
      color: var(--ink);
    }}
    main {{
      max-width: 980px;
      margin: 0 auto;
      padding: 16px 14px calc(104px + env(safe-area-inset-bottom));
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: 0 18px 40px rgba(24,34,47,0.12);
      padding: 16px;
      margin-top: 14px;
    }}
    .screen-wrap {{
      position: relative;
      overflow: hidden;
      border-radius: 20px;
      border: 1px solid var(--line);
      background: #fff;
      margin-top: 14px;
    }}
    #screen {{
      display: block;
      width: 100%;
      height: auto;
      touch-action: none;
      user-select: none;
      -webkit-user-select: none;
      cursor: pointer;
    }}
    .hero {{
      display: grid;
      gap: 8px;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(1.35rem, 4vw, 2rem);
    }}
    p {{
      margin: 0;
      line-height: 1.45;
      font-size: 1rem;
    }}
    .status {{
      display: none;
      margin-top: 8px;
      padding: 10px 12px;
      border-radius: 14px;
      background: rgba(217, 74, 30, 0.08);
      color: #7c2d12;
      font-size: 0.92rem;
      line-height: 1.35;
      white-space: pre-line;
    }}
    .status.visible {{
      display: block;
    }}
    .hint {{
      margin-top: 12px;
      font-size: 0.94rem;
      color: rgba(24,34,47,0.78);
      line-height: 1.4;
    }}
    .assist-bar {{
      position: fixed;
      left: 12px;
      right: 12px;
      bottom: max(12px, env(safe-area-inset-bottom));
      z-index: 35;
      display: flex;
      gap: 10px;
      justify-content: center;
      align-items: center;
      flex-wrap: wrap;
      max-width: 980px;
      margin: 0 auto;
    }}
    .assist-button {{
      border: 1px solid var(--line);
      border-radius: 999px;
      min-height: 48px;
      padding: 12px 18px;
      font: inherit;
      font-size: 15px;
      font-weight: 700;
      background: rgba(255, 255, 255, 0.96);
      color: var(--ink);
      box-shadow: 0 14px 30px rgba(24,34,47,0.14);
      backdrop-filter: blur(12px);
      touch-action: manipulation;
      -webkit-tap-highlight-color: transparent;
    }}
    .assist-button.primary {{
      background: var(--accent);
      color: #fff;
      border-color: transparent;
    }}
    .assist-button.hidden {{
      display: none;
    }}
    .composer {{
      position: fixed;
      left: 12px;
      right: 12px;
      bottom: max(12px, env(safe-area-inset-bottom));
      z-index: 40;
      max-width: 980px;
      margin: 0 auto;
      transform: translateY(calc(100% + 20px));
      transition: transform 0.18s ease;
    }}
    .composer.visible {{
      transform: translateY(0);
    }}
    .composer-card {{
      display: grid;
      gap: 12px;
      padding: 16px;
      border-radius: 24px;
      background: rgba(255, 255, 255, 0.98);
      border: 1px solid var(--line);
      box-shadow: 0 20px 48px rgba(24,34,47,0.18);
      backdrop-filter: blur(12px);
    }}
    .composer-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }}
    .composer-title {{
      font-size: 1rem;
      font-weight: 700;
    }}
    .composer-note {{
      font-size: 0.9rem;
      color: rgba(24,34,47,0.72);
      line-height: 1.35;
    }}
    .composer-input {{
      width: 100%;
      min-height: 92px;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px 16px;
      font: inherit;
      font-size: 16px;
      background: #fff;
      resize: vertical;
    }}
    .composer-actions {{
      display: grid;
      gap: 8px;
      grid-template-columns: repeat(4, 1fr);
    }}
    button {{
      border: none;
      border-radius: 16px;
      min-height: 50px;
      padding: 12px 10px;
      font: inherit;
      font-weight: 600;
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
      font-size: 15px;
      touch-action: manipulation;
      -webkit-tap-highlight-color: transparent;
    }}
    button.primary {{
      background: var(--accent);
      color: #fff;
      border-color: transparent;
    }}
    button.warn {{
      background: var(--accent-2);
      color: #fff;
      border-color: transparent;
    }}
    .ghost-button {{
      background: transparent;
      color: rgba(24,34,47,0.78);
    }}
    .debug-panel {{
      display: grid;
      gap: 10px;
      margin-top: 4px;
      padding-top: 4px;
      border-top: 1px solid var(--line);
    }}
    .debug-title {{
      font-size: 0.88rem;
      font-weight: 700;
      color: rgba(24,34,47,0.7);
    }}
    .debug-grid {{
      display: grid;
      gap: 8px;
      grid-template-columns: repeat(3, 1fr);
    }}
    @media (max-width: 480px) {{
      main {{
        padding-bottom: calc(88px + env(safe-area-inset-bottom));
      }}
      .assist-bar,
      .composer {{
        left: 10px;
        right: 10px;
        bottom: max(10px, env(safe-area-inset-bottom));
      }}
      .assist-button {{
        flex: 1 1 0;
      }}
      .composer-actions,
      .debug-grid {{
        grid-template-columns: repeat(2, 1fr);
      }}
    }}
  </style>
</head>
<body>
  <main>
    <div class="panel">
      <div class="hero">
        <h1>Sign in to continue</h1>
        <p>
          Use this secure browser to log in. As soon as the session is ready,
          Finance Bot will return you to Telegram automatically.
        </p>
      </div>
      <div id="status" class="status" aria-live="polite"></div>
    </div>

    <div class="panel">
      <div class="screen-wrap">
        <img id="screen" alt="Remote browser screen">
      </div>
      <div class="hint">
        Tap the page to interact. Swipe up or down on the page to move.
        Only open the typing drawer when you need phone, email, password, or SMS code input.
      </div>
    </div>
  </main>

  <div class="assist-bar">
    <button class="assist-button primary" id="openComposer">Type or paste</button>
    <button class="assist-button hidden" id="continueTelegram">Return to Telegram</button>
  </div>

  <section class="composer" id="composer" aria-hidden="true">
    <div class="composer-card">
      <div class="composer-head">
        <div>
          <div class="composer-title">Type into the site</div>
          <div class="composer-note">
            Use this only for phone, email, password, one-time codes, or other secure fields.
          </div>
        </div>
        <button class="ghost-button" id="closeComposer">Close</button>
      </div>
      <textarea
        class="composer-input"
        id="textInput"
        placeholder="Phone, email, password, or code"
      ></textarea>
      <div class="composer-actions">
        <button class="primary" id="sendText">Paste into site</button>
        <button id="nextField">Next</button>
        <button id="continueKey">Continue</button>
        <button id="deleteKey">Delete</button>
      </div>
      {debug_panel}
    </div>
  </section>

  <script>
    const token = {safe_token!r};
    const screenEl = document.getElementById('screen');
    const statusEl = document.getElementById('status');
    const textInputEl = document.getElementById('textInput');
    const composerEl = document.getElementById('composer');
    const openComposerEl = document.getElementById('openComposer');
    const closeComposerEl = document.getElementById('closeComposer');
    const continueTelegramEl = document.getElementById('continueTelegram');
    let lastReturnUrl = '';
    let touchStart = null;
    let touchLast = null;
    let wheelLock = false;
    let pollHandle = null;

    function setComposerOpen(open) {{
      composerEl.classList.toggle('visible', open);
      composerEl.setAttribute('aria-hidden', open ? 'false' : 'true');
    }}

    function stopPolling() {{
      if (pollHandle !== null) {{
        window.clearInterval(pollHandle);
        pollHandle = null;
      }}
    }}

    async function fetchState() {{
      const resp = await fetch(`/api/browser-connect/${{token}}/state`, {{ cache: 'no-store' }});
      if (!resp.ok) {{
        throw new Error('state ' + resp.status);
      }}
      return resp.json();
    }}

    function refreshImage() {{
      screenEl.src = `/api/browser-connect/${{token}}/screenshot?ts=${{Date.now()}}`;
    }}

    async function postAction(payload) {{
      const resp = await fetch(`/api/browser-connect/${{token}}/action`, {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(payload),
      }});
      if (!resp.ok) {{
        throw new Error('Server error ' + resp.status);
      }}
      const state = await resp.json();
      updateStatus(state);
      refreshImage();
    }}

    let _actionInFlight = false;

    async function doAction(payload) {{
      if (_actionInFlight) return;
      _actionInFlight = true;
      screenEl.style.opacity = '0.55';
      screenEl.style.pointerEvents = 'none';
      try {{
        await postAction(payload);
      }} catch (err) {{
        statusEl.classList.add('visible');
        statusEl.textContent = 'Action failed: ' + err.message + '. Try again.';
      }} finally {{
        _actionInFlight = false;
        screenEl.style.opacity = '1';
        screenEl.style.pointerEvents = '';
      }}
    }}

    function updateStatus(state) {{
      if (state.error) {{
        statusEl.classList.add('visible');
        statusEl.textContent = state.error;
      }} else {{
        statusEl.classList.remove('visible');
        statusEl.textContent = '';
      }}
      lastReturnUrl = state.return_url || '';
      continueTelegramEl.classList.toggle('hidden', !lastReturnUrl);
      if (state.status === 'expired') {{
        stopPolling();
        statusEl.classList.add('visible');
        statusEl.textContent = 'This sign-in session expired. Return to Telegram and start again.';
        continueTelegramEl.classList.remove('hidden');
        return;
      }}
      if (state.status === 'completed' && lastReturnUrl) {{
        stopPolling();
        window.location.replace(lastReturnUrl);
      }}
    }}

    async function reloadAll() {{
      refreshImage();
      const state = await fetchState();
      updateStatus(state);
    }}

    screenEl.addEventListener('click', async (event) => {{
      const rect = screenEl.getBoundingClientRect();
      const scaleX = screenEl.naturalWidth / rect.width;
      const scaleY = screenEl.naturalHeight / rect.height;
      const x = (event.clientX - rect.left) * scaleX;
      const y = (event.clientY - rect.top) * scaleY;
      await doAction({{ action: 'click', x, y }});
    }});

    screenEl.addEventListener('wheel', async (event) => {{
      event.preventDefault();
      if (wheelLock) {{
        return;
      }}
      wheelLock = true;
      try {{
        await doAction({{ action: 'scroll', delta_y: event.deltaY }});
      }} finally {{
        window.setTimeout(() => {{
          wheelLock = false;
        }}, 120);
      }}
    }}, {{ passive: false }});

    screenEl.addEventListener('touchstart', (event) => {{
      const touch = event.touches[0];
      touchStart = touch;
      touchLast = touch;
    }}, {{ passive: true }});

    screenEl.addEventListener('touchmove', (event) => {{
      touchLast = event.touches[0];
      event.preventDefault();
    }}, {{ passive: false }});

    screenEl.addEventListener('touchend', async (event) => {{
      if (!touchStart) {{
        return;
      }}
      const rect = screenEl.getBoundingClientRect();
      const scaleX = screenEl.naturalWidth / rect.width;
      const scaleY = screenEl.naturalHeight / rect.height;
      const finalTouch = touchLast || event.changedTouches[0];
      const deltaY = touchStart.clientY - finalTouch.clientY;
      const deltaX = touchStart.clientX - finalTouch.clientX;
      touchStart = null;
      touchLast = null;

      if (Math.abs(deltaY) > 18 || Math.abs(deltaX) > 18) {{
        await postAction({{ action: 'scroll', delta_y: deltaY * 2.4 }});
        return;
      }}

      const x = (finalTouch.clientX - rect.left) * scaleX;
      const y = (finalTouch.clientY - rect.top) * scaleY;
      await doAction({{ action: 'click', x, y }});
    }});

    openComposerEl.addEventListener('click', () => {{
      setComposerOpen(true);
      textInputEl.focus();
    }});
    closeComposerEl.addEventListener('click', () => setComposerOpen(false));

    document.getElementById('sendText').addEventListener('click', async () => {{
      if (!textInputEl.value) return;
      const val = textInputEl.value;
      textInputEl.value = '';
      setComposerOpen(false);
      await doAction({{ action: 'type', text: val }});
    }});
    document.getElementById('nextField').addEventListener(
      'click',
      () => doAction({{ action: 'press', key: 'tab' }})
    );
    document.getElementById('continueKey').addEventListener(
      'click',
      () => doAction({{ action: 'press', key: 'enter' }})
    );
    document.getElementById('deleteKey').addEventListener(
      'click',
      () => doAction({{ action: 'press', key: 'backspace' }})
    );
    continueTelegramEl.addEventListener('click', () => {{
      if (lastReturnUrl) {{
        window.location.href = lastReturnUrl;
      }}
    }});

    {debug_js}

    reloadAll();
    pollHandle = setInterval(async () => {{
      try {{
        const state = await fetchState();
        updateStatus(state);
        if (state.status === 'active') {{
          refreshImage();
        }}
      }} catch (error) {{
        stopPolling();
        statusEl.classList.add('visible');
        statusEl.textContent = 'Connection issue. Pull to refresh the page and try again.';
      }}
    }}, 2500);
  </script>
</body>
</html>"""


async def _build_return_url(token: str) -> str:
    bot_username = await get_bot_username()
    if not bot_username:
        return ""
    return f"https://t.me/{bot_username}?start=browser_connect_{token}"


def _expired_state_response() -> BrowserConnectStateResponse:
    return BrowserConnectStateResponse(
        ok=False,
        status="expired",
        provider="",
        current_url="",
        error="This sign-in session expired. Return to Telegram and start again.",
        return_url="",
    )


def _expired_screenshot_response() -> Response:
    return Response(content=_BLANK_SCREENSHOT_PNG, media_type="image/png")


@router.get("/{token}", response_class=HTMLResponse)
async def browser_connect_page(
    request: Request,
    token: str,
    debug: bool = Query(False),
) -> HTMLResponse:
    try:
        state = await remote_browser_connect.get_session_state(
            token,
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return HTMLResponse(_render_connect_page(token, state["provider"], debug=debug))


@router.get("/{token}/state", response_model=BrowserConnectStateResponse)
async def browser_connect_state(request: Request, token: str) -> BrowserConnectStateResponse:
    try:
        state = await remote_browser_connect.get_session_state(
            token,
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as exc:
        if "expired" in str(exc).lower():
            return _expired_state_response()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return_url = ""
    if state["status"] == "completed":
        return_url = await _build_return_url(token)

    return BrowserConnectStateResponse(
        ok=True,
        status=state["status"],
        provider=state["provider"],
        current_url=state["current_url"],
        error=state.get("error", ""),
        return_url=return_url,
    )


@router.get("/{token}/screenshot")
async def browser_connect_screenshot(token: str) -> Response:
    try:
        image = await remote_browser_connect.get_session_screenshot(token)
    except ValueError as exc:
        if "expired" in str(exc).lower():
            return _expired_screenshot_response()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=image, media_type="image/png")


@router.post("/{token}/action", response_model=BrowserConnectStateResponse)
async def browser_connect_action(
    token: str,
    body: BrowserConnectActionRequest,
) -> BrowserConnectStateResponse:
    try:
        state = await remote_browser_connect.apply_action(
            token,
            action=body.action,
            x=body.x,
            y=body.y,
            text=body.text,
            key=body.key,
            delta_y=body.delta_y,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return_url = ""
    if state["status"] == "completed":
        return_url = await _build_return_url(token)

    return BrowserConnectStateResponse(
        ok=True,
        status=state["status"],
        provider=state["provider"],
        current_url=state["current_url"],
        error=state.get("error", ""),
        return_url=return_url,
    )
