"""Pydantic models for browser extension API."""

from pydantic import BaseModel, Field


class CookieItem(BaseModel):
    name: str
    value: str
    domain: str
    path: str = "/"
    expires: float = -1
    http_only: bool = Field(False, alias="httpOnly")
    secure: bool = False
    same_site: str = Field("None", alias="sameSite")

    model_config = {"populate_by_name": True}


class SaveSessionRequest(BaseModel):
    site: str
    cookies: list[CookieItem]


class SaveSessionResponse(BaseModel):
    ok: bool
    site: str


class SessionInfo(BaseModel):
    site: str
    cookie_count: int
    updated_at: str


class ListSessionsResponse(BaseModel):
    sessions: list[SessionInfo]


class ExtensionStatusResponse(BaseModel):
    ok: bool
    user_id: str
    family_id: str
    session_count: int
    sites: list[str]
    bot_username: str = ""
