"""Hosted browser connect UI for phone and desktop login flows."""

from __future__ import annotations

import html

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

from api.browser_extension import get_bot_username
from api.schemas.browser_connect import BrowserConnectActionRequest, BrowserConnectStateResponse
from src.tools import remote_browser_connect

router = APIRouter(prefix="/api/browser-connect", tags=["browser-connect"])


def _render_connect_page(token: str, provider: str) -> str:
    safe_token = html.escape(token)
    safe_provider = html.escape(provider)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Connect {safe_provider}</title>
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
      max-width: 760px;
      margin: 0 auto;
      padding: 18px 14px 40px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: 0 18px 40px rgba(24,34,47,0.12);
      padding: 16px;
      margin-top: 14px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: clamp(1.5rem, 4vw, 2.2rem);
    }}
    p {{
      margin: 0;
      line-height: 1.45;
    }}
    .status {{
      margin-top: 10px;
      font-size: 0.95rem;
      white-space: pre-line;
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
    .controls {{
      display: grid;
      gap: 10px;
      margin-top: 14px;
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
    }}
    button {{
      border: none;
      border-radius: 16px;
      padding: 12px;
      font: inherit;
      font-weight: 600;
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
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
      margin-top: 12px;
      font-size: 0.92rem;
      color: rgba(24,34,47,0.78);
    }}
  </style>
</head>
<body>
  <main>
    <div class="panel">
      <h1>Connect {safe_provider}</h1>
      <p>
        Log in inside this secure browser. When the session is ready,
        Finance Bot will return you to Telegram automatically.
      </p>
      <div id="status" class="status">Preparing secure browser...</div>
    </div>

    <div class="panel">
      <div class="screen-wrap">
        <img id="screen" alt="Remote browser screen">
      </div>
      <div class="controls">
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
          <button class="warn" id="openTelegram">Open Telegram</button>
        </div>
      </div>
      <div class="hint">
        Tap directly on the screenshot to click. Use Send, Tab, and Enter
        to fill forms, password fields, SMS codes, or 2FA prompts.
      </div>
    </div>
  </main>

  <script>
    const token = {safe_token!r};
    const screenEl = document.getElementById('screen');
    const statusEl = document.getElementById('status');
    const textInputEl = document.getElementById('textInput');
    let lastReturnUrl = '';

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
      const lines = [
        `Status: ${{state.status}}`,
        `Provider: ${{state.provider}}`,
        `URL: ${{state.current_url || 'loading...'}}`,
      ];
      if (state.error) {{
        lines.push(`Issue: ${{state.error}}`);
      }}
      statusEl.textContent = lines.join('\\n');
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
      const rect = screenEl.getBoundingClientRect();
      const scaleX = screenEl.naturalWidth / rect.width;
      const scaleY = screenEl.naturalHeight / rect.height;
      const x = (event.clientX - rect.left) * scaleX;
      const y = (event.clientY - rect.top) * scaleY;
      await postAction({{ action: 'click', x, y }});
    }});

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

    reloadAll();
    setInterval(async () => {{
      try {{
        const state = await fetchState();
        updateStatus(state);
        refreshImage();
      }} catch (error) {{
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
async def browser_connect_page(token: str) -> HTMLResponse:
    try:
        state = await remote_browser_connect.get_session_state(token)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return HTMLResponse(_render_connect_page(token, state["provider"]))


@router.get("/{token}/state", response_model=BrowserConnectStateResponse)
async def browser_connect_state(token: str) -> BrowserConnectStateResponse:
    try:
        state = await remote_browser_connect.get_session_state(token)
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
