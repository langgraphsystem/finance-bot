"""Tests for Vercel deployment client."""

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.deploy.vercel import (
    _build_flask_files,
    _build_static_files,
    _is_static,
    deploy,
    is_configured,
)

# --- is_configured ---


def test_is_configured_false():
    with patch("src.core.deploy.vercel.settings") as mock_settings:
        mock_settings.vercel_token = ""
        assert is_configured() is False


def test_is_configured_true():
    with patch("src.core.deploy.vercel.settings") as mock_settings:
        mock_settings.vercel_token = "tok_abc123"
        assert is_configured() is True


# --- _is_static ---


def test_is_static_html():
    assert _is_static("<html></html>", ".html") is True


def test_is_static_css():
    assert _is_static("body { color: red; }", ".css") is True


def test_is_static_js_without_server():
    assert _is_static("console.log('hello');", ".js") is True


def test_is_static_js_with_express():
    assert _is_static("const app = require('express')()", ".js") is False


def test_is_static_python():
    assert _is_static("from flask import Flask", ".py") is False


# --- _build_static_files ---


def test_build_static_files_html():
    files = _build_static_files("<h1>Hi</h1>", "page.html")
    assert len(files) == 1
    assert files[0]["file"] == "index.html"
    decoded = base64.b64decode(files[0]["data"]).decode("utf-8")
    assert decoded == "<h1>Hi</h1>"


def test_build_static_files_js():
    files = _build_static_files("alert(1);", "app.js")
    assert len(files) == 1
    assert files[0]["file"] == "app.js"


# --- _build_flask_files ---


def test_build_flask_files_structure():
    code = (
        "# pip install flask requests\n"
        "from flask import Flask\n"
        "app = Flask(__name__)\n"
        "app.run(host='0.0.0.0', port=5000)\n"
    )
    files = _build_flask_files(code)
    filenames = [f["file"] for f in files]
    assert "api/index.py" in filenames
    assert "requirements.txt" in filenames
    assert "vercel.json" in filenames


def test_build_flask_files_strips_app_run():
    code = (
        "from flask import Flask\n"
        "app = Flask(__name__)\n\n"
        "@app.route('/')\n"
        "def index():\n"
        "    return 'hi'\n\n"
        "app.run(host='0.0.0.0', port=5000)\n"
    )
    files = _build_flask_files(code)
    api_file = next(f for f in files if f["file"] == "api/index.py")
    decoded = base64.b64decode(api_file["data"]).decode("utf-8")
    assert "app.run(" not in decoded
    assert "from flask import Flask" in decoded


def test_build_flask_files_extracts_deps():
    code = "# pip install flask pandas numpy\nfrom flask import Flask\napp.run()\n"
    files = _build_flask_files(code)
    req_file = next(f for f in files if f["file"] == "requirements.txt")
    reqs = base64.b64decode(req_file["data"]).decode("utf-8")
    assert "flask" in reqs
    assert "pandas" in reqs
    assert "numpy" in reqs


def test_build_flask_files_vercel_config():
    code = "from flask import Flask\napp = Flask(__name__)\napp.run()\n"
    files = _build_flask_files(code)
    config_file = next(f for f in files if f["file"] == "vercel.json")
    config = json.loads(base64.b64decode(config_file["data"]).decode("utf-8"))
    assert config["rewrites"][0]["source"] == "/(.*)"
    assert config["rewrites"][0]["destination"] == "/api/index"


# --- deploy() ---


def _make_mock_response(status_code, json_data, text=""):
    """Create a MagicMock httpx response (json() is sync in httpx)."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.headers = {"content-type": "application/json"}
    resp.text = text or json.dumps(json_data)
    return resp


async def test_deploy_no_token():
    with patch("src.core.deploy.vercel.settings") as mock_settings:
        mock_settings.vercel_token = ""
        result = await deploy("<h1>Hi</h1>", "page.html", ".html", "abc123")
    assert result.error == "Vercel token not configured"
    assert result.url is None


async def test_deploy_unsupported_extension():
    with patch("src.core.deploy.vercel.settings") as mock_settings:
        mock_settings.vercel_token = "tok_abc"
        result = await deploy("fn main() {}", "app.rs", ".rs", "abc123")
    assert result.error is not None
    assert "not supported" in result.error


async def test_deploy_static_success():
    mock_response = _make_mock_response(
        200,
        {
            "url": "app-abc123.vercel.app",
            "id": "dpl_123",
        },
    )

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.core.deploy.vercel.settings") as mock_settings,
        patch("src.core.deploy.vercel.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.vercel_token = "tok_abc"
        mock_settings.vercel_team_id = ""
        result = await deploy("<h1>Hi</h1>", "page.html", ".html", "abc123")

    assert result.url == "https://app-abc123.vercel.app"
    assert result.deployment_id == "dpl_123"
    assert result.error is None

    # Verify API call
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert "/v13/deployments" in call_kwargs[0][0]
    body = call_kwargs[1]["json"]
    assert body["name"] == "app-abc123"
    assert len(body["files"]) == 1
    assert body["files"][0]["file"] == "index.html"


async def test_deploy_flask_success():
    mock_response = _make_mock_response(
        201,
        {
            "url": "https://app-xyz.vercel.app",
            "id": "dpl_456",
        },
    )

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    flask_code = (
        "# pip install flask\n"
        "from flask import Flask\n"
        "app = Flask(__name__)\n\n"
        "@app.route('/')\n"
        "def index():\n"
        "    return 'hello'\n\n"
        "app.run(host='0.0.0.0', port=5000)\n"
    )

    with (
        patch("src.core.deploy.vercel.settings") as mock_settings,
        patch("src.core.deploy.vercel.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.vercel_token = "tok_abc"
        mock_settings.vercel_team_id = "team_123"
        result = await deploy(flask_code, "app.py", ".py", "xyz")

    assert result.url == "https://app-xyz.vercel.app"

    # Verify team_id passed as query param
    call_kwargs = mock_client.post.call_args
    assert call_kwargs[1]["params"]["teamId"] == "team_123"

    # Verify Flask files structure
    body = call_kwargs[1]["json"]
    filenames = [f["file"] for f in body["files"]]
    assert "api/index.py" in filenames
    assert "requirements.txt" in filenames
    assert "vercel.json" in filenames


async def test_deploy_api_error():
    mock_response = _make_mock_response(
        403,
        {"error": {"message": "Invalid token"}},
        text="Invalid token",
    )

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.core.deploy.vercel.settings") as mock_settings,
        patch("src.core.deploy.vercel.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.vercel_token = "bad_token"
        mock_settings.vercel_team_id = ""
        result = await deploy("<h1>Hi</h1>", "page.html", ".html", "abc")

    assert result.url is None
    assert "Invalid token" in result.error


async def test_deploy_timeout():
    import httpx

    mock_client = AsyncMock()
    mock_client.post.side_effect = httpx.TimeoutException("timeout")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.core.deploy.vercel.settings") as mock_settings,
        patch("src.core.deploy.vercel.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.vercel_token = "tok_abc"
        mock_settings.vercel_team_id = ""
        result = await deploy("<h1>Hi</h1>", "page.html", ".html", "abc")

    assert result.url is None
    assert "timed out" in result.error


async def test_deploy_url_gets_https_prefix():
    """URL without https:// prefix gets it added."""
    mock_response = _make_mock_response(
        200,
        {
            "url": "my-app-123.vercel.app",
            "id": "dpl_789",
        },
    )

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.core.deploy.vercel.settings") as mock_settings,
        patch("src.core.deploy.vercel.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.vercel_token = "tok"
        mock_settings.vercel_team_id = ""
        result = await deploy("<h1>Hi</h1>", "page.html", ".html", "abc")

    assert result.url == "https://my-app-123.vercel.app"
