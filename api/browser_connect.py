"""Hosted browser connect UI for phone and desktop login flows."""

from __future__ import annotations

import html

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from api.browser_extension import get_bot_username
from api.schemas.browser_connect import BrowserConnectActionRequest, BrowserConnectStateResponse
from src.tools import remote_browser_connect

router = APIRouter(prefix="/api/browser-connect", tags=["browser-connect"])


def _render_connect_page(token: str, provider: str) -> str:
    safe_token = html.escape(token)
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
      max-width: 1240px;
      margin: 0 auto;
      padding: 16px 14px calc(96px + env(safe-area-inset-bottom));
    }}
    .workspace {{
      display: grid;
      gap: 14px;
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
      touch-action: manipulation;
      user-select: none;
      -webkit-user-select: none;
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
    .dock {{
      position: fixed;
      left: 12px;
      right: 12px;
      bottom: max(12px, env(safe-area-inset-bottom));
      z-index: 30;
      max-width: 760px;
      margin: 0 auto;
    }}
    .controls {{
      display: grid;
      gap: 10px;
      padding: 14px;
      border-radius: 24px;
      background: rgba(255, 255, 255, 0.96);
      border: 1px solid var(--line);
      box-shadow: 0 18px 48px rgba(24,34,47,0.18);
      backdrop-filter: blur(12px);
    }}
    .controls-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }}
    .controls-title {{
      font-size: 0.98rem;
      font-weight: 700;
    }}
    .controls-actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .controls-body {{
      display: grid;
      gap: 10px;
    }}
    .dock.collapsed .controls-body {{
      display: none;
    }}
    .row {{
      display: grid;
      gap: 8px;
      grid-template-columns: repeat(3, 1fr);
    }}
    .row.compact {{
      grid-template-columns: repeat(4, 1fr);
    }}
    input {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
      font: inherit;
      font-size: 16px;
      background: #fff;
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
    .hint {{
      font-size: 0.92rem;
      color: rgba(24,34,47,0.78);
      line-height: 1.35;
    }}
    @media (max-width: 480px) {{
      main {{
        padding-bottom: calc(86px + env(safe-area-inset-bottom));
      }}
      .dock {{
        left: 10px;
        right: 10px;
        bottom: max(10px, env(safe-area-inset-bottom));
      }}
      .controls {{
        padding: 12px;
        border-radius: 20px;
      }}
      .controls-head {{
        align-items: stretch;
      }}
      .controls-actions {{
        width: 100%;
      }}
      .controls-actions button {{
        flex: 1 1 0;
      }}
      .row,
      .row.compact {{
        grid-template-columns: repeat(2, 1fr);
      }}
    }}
    @media (min-width: 900px) {{
      main {{
        padding: 20px 16px 24px;
      }}
      .workspace {{
        grid-template-columns: minmax(0, 1fr) 340px;
        align-items: start;
      }}
      .screen-panel {{
        min-width: 0;
      }}
      .dock {{
        position: sticky;
        top: 20px;
        left: auto;
        right: auto;
        bottom: auto;
        max-width: none;
      }}
      .controls {{
        padding: 16px;
      }}
      .controls-body {{
        display: grid;
      }}
      .controls-actions {{
        justify-content: flex-start;
      }}
      .row,
      .row.compact {{
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

    <div class="workspace">
      <div class="panel screen-panel">
        <div class="screen-wrap">
          <img id="screen" alt="Remote browser screen">
        </div>
      </div>

      <div class="dock">
        <div class="controls">
          <div class="controls-head">
            <div class="controls-title">Browser controls</div>
            <div class="controls-actions">
              <button id="toggleControls">Show Controls</button>
              <button class="warn" id="openTelegram">Open Telegram</button>
            </div>
          </div>
          <div class="controls-body" id="controlsBody">
            <input id="textInput" type="text" placeholder="Type text here, then tap Send">
            <div class="row">
              <button class="primary" id="sendText">Send</button>
              <button id="tabKey">Tab</button>
              <button id="enterKey">Enter</button>
            </div>
            <div class="row compact">
              <button id="backspaceKey">Backspace</button>
              <button id="scrollUp">Scroll Up</button>
              <button id="scrollDown">Scroll Down</button>
              <button id="refreshPage">Refresh</button>
            </div>
            <div class="row">
              <button id="backPage">Back</button>
              <button id="reloadScreen">Reload Screen</button>
            </div>
            <div class="hint">
              Tap directly on the screenshot to click. Open controls only when you need
              typing, Enter, Tab, SMS codes, or scrolling.
            </div>
          </div>
        </div>
      </div>
    </div>
  </main>

  <script>
    const token = {safe_token!r};
    const screenEl = document.getElementById('screen');
    const statusEl = document.getElementById('status');
    const textInputEl = document.getElementById('textInput');
    const dockEl = document.querySelector('.dock');
    const toggleControlsEl = document.getElementById('toggleControls');
    let lastReturnUrl = '';

    function isDesktopLayout() {{
      return window.innerWidth >= 900;
    }}

    function setControlsCollapsed(collapsed) {{
      if (isDesktopLayout()) {{
        dockEl.classList.remove('collapsed');
        toggleControlsEl.textContent = 'Controls Ready';
        toggleControlsEl.disabled = true;
        return;
      }}
      toggleControlsEl.disabled = false;
      dockEl.classList.toggle('collapsed', collapsed);
      toggleControlsEl.textContent = collapsed ? 'Show Controls' : 'Hide Controls';
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
        throw new Error('action ' + resp.status);
      }}
      const state = await resp.json();
      updateStatus(state);
      refreshImage();
    }}

    function updateStatus(state) {{
      if (state.error) {{
        statusEl.classList.add('visible');
        statusEl.textContent = 'Connection issue. Reload the screen and try again.';
      }} else {{
        statusEl.classList.remove('visible');
        statusEl.textContent = '';
      }}
      lastReturnUrl = state.return_url || '';
      if (state.status === 'completed' && lastReturnUrl) {{
        window.location.replace(lastReturnUrl);
      }}
    }}

    async function reloadAll() {{
      refreshImage();
      const state = await fetchState();
      updateStatus(state);
    }}

    screenEl.addEventListener('click', async (event) => {{
      if (dockEl.classList.contains('collapsed') === false && !isDesktopLayout()) {{
        setControlsCollapsed(true);
      }}
      const rect = screenEl.getBoundingClientRect();
      const scaleX = screenEl.naturalWidth / rect.width;
      const scaleY = screenEl.naturalHeight / rect.height;
      const x = (event.clientX - rect.left) * scaleX;
      const y = (event.clientY - rect.top) * scaleY;
      await postAction({{ action: 'click', x, y }});
    }});

    toggleControlsEl.addEventListener('click', () => {{
      setControlsCollapsed(!dockEl.classList.contains('collapsed'));
    }});

    textInputEl.addEventListener('focus', () => setControlsCollapsed(false));

    document.getElementById('sendText').addEventListener('click', async () => {{
      if (!textInputEl.value) return;
      await postAction({{ action: 'type', text: textInputEl.value }});
      textInputEl.value = '';
    }});
    document.getElementById('tabKey').addEventListener(
      'click',
      () => postAction({{ action: 'press', key: 'tab' }})
    );
    document.getElementById('enterKey').addEventListener(
      'click',
      () => postAction({{ action: 'press', key: 'enter' }})
    );
    document.getElementById('backspaceKey').addEventListener(
      'click',
      () => postAction({{ action: 'press', key: 'backspace' }})
    );
    document.getElementById('scrollUp').addEventListener(
      'click',
      () => postAction({{ action: 'scroll', delta_y: -650 }})
    );
    document.getElementById('scrollDown').addEventListener(
      'click',
      () => postAction({{ action: 'scroll', delta_y: 650 }})
    );
    document.getElementById('refreshPage').addEventListener(
      'click',
      () => postAction({{ action: 'refresh' }})
    );
    document.getElementById('backPage').addEventListener(
      'click',
      () => postAction({{ action: 'back' }})
    );
    document.getElementById('reloadScreen').addEventListener('click', () => reloadAll());
    document.getElementById('openTelegram').addEventListener('click', () => {{
      if (lastReturnUrl) {{
        window.location.href = lastReturnUrl;
      }}
    }});

    setControlsCollapsed(!isDesktopLayout());
    reloadAll();
    window.addEventListener('resize', () => setControlsCollapsed(!isDesktopLayout()));
    setInterval(async () => {{
      try {{
        const state = await fetchState();
        updateStatus(state);
        refreshImage();
      }} catch (error) {{
        statusEl.classList.add('visible');
        statusEl.textContent = 'Connection issue. Pull to refresh or tap Reload Screen.';
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


@router.get("/{token}", response_class=HTMLResponse)
async def browser_connect_page(request: Request, token: str) -> HTMLResponse:
    try:
        state = await remote_browser_connect.get_session_state(
            token,
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return HTMLResponse(_render_connect_page(token, state["provider"]))


@router.get("/{token}/state", response_model=BrowserConnectStateResponse)
async def browser_connect_state(request: Request, token: str) -> BrowserConnectStateResponse:
    try:
        state = await remote_browser_connect.get_session_state(
            token,
            user_agent=request.headers.get("user-agent"),
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


@router.get("/{token}/screenshot")
async def browser_connect_screenshot(token: str) -> Response:
    try:
        image = await remote_browser_connect.get_session_screenshot(token)
    except ValueError as exc:
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
