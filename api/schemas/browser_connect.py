"""Schemas for hosted browser connect flow."""

from pydantic import BaseModel


class BrowserConnectActionRequest(BaseModel):
    action: str
    x: float | None = None
    y: float | None = None
    text: str | None = None
    key: str | None = None
    delta_y: float | None = None


class BrowserConnectStateResponse(BaseModel):
    ok: bool
    status: str
    provider: str
    current_url: str
    error: str = ""
    return_url: str = ""
