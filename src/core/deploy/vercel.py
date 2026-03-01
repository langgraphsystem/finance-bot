"""Vercel deployment client — deploy generated apps to permanent URLs.

Supports two modes:
- Static (HTML/CSS/JS) → deployed as-is, zero cold start
- Python (Flask) → converted to Vercel serverless function

Uses Vercel REST API v13: https://vercel.com/docs/rest-api/endpoints/deployments
"""

import base64
import json
import logging
import re
from dataclasses import dataclass

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)

VERCEL_API = "https://api.vercel.com"
DEPLOY_TIMEOUT = 60  # seconds


@dataclass
class DeployResult:
    """Result of a Vercel deployment."""

    url: str | None = None
    error: str | None = None
    deployment_id: str | None = None


def is_configured() -> bool:
    """Check if Vercel token is set."""
    return bool(settings.vercel_token)


def _is_static(code: str, ext: str) -> bool:
    """Check if the code is a standalone HTML/CSS/JS file (no backend)."""
    if ext in (".html", ".css"):
        return True
    if ext == ".js" and not re.search(
        r"(require\s*\(\s*['\"]express|createServer|Deno\.serve)", code
    ):
        return True
    return False


def _build_static_files(code: str, filename: str) -> list[dict]:
    """Build Vercel file list for a static HTML/JS/CSS deployment."""
    encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
    # Serve as index.html for single-page apps
    target = "index.html" if filename.endswith((".html", ".css")) else filename
    return [{"file": target, "data": encoded, "encoding": "base64"}]


def _build_flask_files(code: str) -> list[dict]:
    """Convert a Flask app to Vercel serverless function format.

    Vercel Python runtime expects:
    - api/index.py with a WSGI/ASGI app
    - requirements.txt
    - vercel.json with rewrite rules
    """
    # Strip the app.run() call — Vercel handles serving
    cleaned = re.sub(
        r"\nif\s+__name__\s*==\s*['\"]__main__['\"]:\s*\n\s+app\.run\([^)]*\)",
        "",
        code,
    )
    cleaned = re.sub(r"\napp\.run\([^)]*\)\s*$", "", cleaned, flags=re.MULTILINE)

    # Extract pip dependencies from comments
    deps = {"flask"}
    for line in code.split("\n"):
        match = re.match(r"#\s*pip install\s+(.+)", line.strip())
        if match:
            for pkg in match.group(1).split():
                deps.add(pkg.strip().lower())
    requirements = "\n".join(sorted(deps)) + "\n"

    vercel_config = json.dumps(
        {"rewrites": [{"source": "/(.*)", "destination": "/api/index"}]},
    )

    return [
        {
            "file": "api/index.py",
            "data": base64.b64encode(cleaned.encode("utf-8")).decode("ascii"),
            "encoding": "base64",
        },
        {
            "file": "requirements.txt",
            "data": base64.b64encode(requirements.encode("utf-8")).decode("ascii"),
            "encoding": "base64",
        },
        {
            "file": "vercel.json",
            "data": base64.b64encode(vercel_config.encode("utf-8")).decode("ascii"),
            "encoding": "base64",
        },
    ]


async def deploy(code: str, filename: str, ext: str, project_suffix: str) -> DeployResult:
    """Deploy code to Vercel and return a permanent URL.

    Args:
        code: Source code to deploy.
        filename: Original filename (e.g. "todo_app.py").
        ext: File extension (e.g. ".py", ".html").
        project_suffix: Unique suffix for the project name (e.g. prog_id).

    Returns:
        DeployResult with permanent URL or error.
    """
    if not settings.vercel_token:
        return DeployResult(error="Vercel token not configured")

    static = _is_static(code, ext)

    if static:
        files = _build_static_files(code, filename)
    elif ext == ".py":
        files = _build_flask_files(code)
    else:
        return DeployResult(error=f"Deployment not supported for {ext} files")

    project_name = f"app-{project_suffix}"

    body: dict = {
        "name": project_name,
        "files": files,
        "projectSettings": {"framework": None},
        "target": "production",
    }

    headers = {
        "Authorization": f"Bearer {settings.vercel_token}",
        "Content-Type": "application/json",
    }

    params = {}
    if settings.vercel_team_id:
        params["teamId"] = settings.vercel_team_id

    try:
        async with httpx.AsyncClient(timeout=DEPLOY_TIMEOUT) as client:
            resp = await client.post(
                f"{VERCEL_API}/v13/deployments",
                headers=headers,
                json=body,
                params=params,
            )

        if resp.status_code in (200, 201):
            data = resp.json()
            url = data.get("url", "")
            if url and not url.startswith("https://"):
                url = f"https://{url}"
            return DeployResult(
                url=url,
                deployment_id=data.get("id"),
            )

        error_data = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        error_msg = error_data.get("error", {}).get("message", resp.text[:200])
        logger.error("Vercel deploy failed: %s %s", resp.status_code, error_msg)
        return DeployResult(error=f"Deploy failed: {error_msg}")

    except httpx.TimeoutException:
        return DeployResult(error="Vercel deploy timed out")
    except Exception as e:
        logger.exception("Vercel deploy error")
        return DeployResult(error=f"Deploy error: {e}")
