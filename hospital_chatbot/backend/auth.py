"""Admin authentication and role-based authorization helpers.

Supports two auth methods:
- X-Admin-Token header
- HTTP Basic Auth header

Roles:
- viewer: read-only admin access
- editor: can upload/rebuild/run evaluation
- admin: full access

Environment variables (examples):
- ADMIN_AUTH_DISABLED=false
- ADMIN_AUTH_MODE=either            # either | token | basic
- ADMIN_TOKEN=super-secret          # fallback admin token
- ADMIN_VIEWER_TOKEN=...
- ADMIN_EDITOR_TOKEN=...
- ADMIN_ADMIN_TOKEN=...
- ADMIN_USERNAME=admin              # fallback admin basic username
- ADMIN_PASSWORD=change-me
- ADMIN_VIEWER_USERNAME=...
- ADMIN_VIEWER_PASSWORD=...
- ADMIN_EDITOR_USERNAME=...
- ADMIN_EDITOR_PASSWORD=...
- ADMIN_ADMIN_USERNAME=...
- ADMIN_ADMIN_PASSWORD=...
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Callable, Literal

from fastapi import Depends, Header, HTTPException

Role = Literal["viewer", "editor", "admin"]
_ROLE_ORDER: dict[Role, int] = {"viewer": 1, "editor": 2, "admin": 3}


@dataclass
class AdminPrincipal:
    role: Role
    auth_type: str
    subject: str


class AuthConfig:
    def __init__(self) -> None:
        self.disabled = os.getenv("ADMIN_AUTH_DISABLED", "false").lower() in {"1", "true", "yes"}
        self.mode = os.getenv("ADMIN_AUTH_MODE", "either").lower()
        self.tokens: dict[str, Role] = {}
        self.users: dict[str, tuple[str, Role]] = {}
        self._load_tokens()
        self._load_users()

    def _load_tokens(self) -> None:
        fallback = os.getenv("ADMIN_TOKEN")
        if fallback:
            self.tokens[fallback] = "admin"
        mapping = {
            os.getenv("ADMIN_VIEWER_TOKEN"): "viewer",
            os.getenv("ADMIN_EDITOR_TOKEN"): "editor",
            os.getenv("ADMIN_ADMIN_TOKEN"): "admin",
        }
        for token, role in mapping.items():
            if token:
                self.tokens[token] = role  # type: ignore[assignment]

    def _load_users(self) -> None:
        fallback_user = os.getenv("ADMIN_USERNAME")
        fallback_pass = os.getenv("ADMIN_PASSWORD")
        if fallback_user and fallback_pass:
            self.users[fallback_user] = (fallback_pass, "admin")
        specs = [
            ("ADMIN_VIEWER_USERNAME", "ADMIN_VIEWER_PASSWORD", "viewer"),
            ("ADMIN_EDITOR_USERNAME", "ADMIN_EDITOR_PASSWORD", "editor"),
            ("ADMIN_ADMIN_USERNAME", "ADMIN_ADMIN_PASSWORD", "admin"),
        ]
        for u_key, p_key, role in specs:
            username = os.getenv(u_key)
            password = os.getenv(p_key)
            if username and password:
                self.users[username] = (password, role)  # type: ignore[assignment]


CONFIG = AuthConfig()


def _parse_basic(authorization: str | None) -> tuple[str, str] | None:
    if not authorization:
        return None
    prefix = "basic "
    if not authorization.lower().startswith(prefix):
        return None
    token = authorization[len(prefix):].strip()
    try:
        decoded = base64.b64decode(token).decode("utf-8")
    except Exception:
        return None
    if ":" not in decoded:
        return None
    username, password = decoded.split(":", 1)
    return username, password


def authenticate_admin(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> AdminPrincipal:
    if CONFIG.disabled:
        return AdminPrincipal(role="admin", auth_type="disabled", subject="auth-disabled")

    mode = CONFIG.mode
    basic_creds = _parse_basic(authorization)

    def token_ok() -> AdminPrincipal | None:
        if x_admin_token and x_admin_token in CONFIG.tokens:
            role = CONFIG.tokens[x_admin_token]
            return AdminPrincipal(role=role, auth_type="token", subject=f"token:{role}")
        return None

    def basic_ok() -> AdminPrincipal | None:
        if basic_creds:
            username, password = basic_creds
            expected = CONFIG.users.get(username)
            if expected and expected[0] == password:
                return AdminPrincipal(role=expected[1], auth_type="basic", subject=username)
        return None

    principal: AdminPrincipal | None = None
    if mode == "token":
        principal = token_ok()
    elif mode == "basic":
        principal = basic_ok()
    else:
        principal = token_ok() or basic_ok()

    if principal is None:
        raise HTTPException(
            status_code=401,
            detail="Admin authentication required",
            headers={"WWW-Authenticate": "Basic realm=admin"},
        )
    return principal


def require_role(min_role: Role) -> Callable[..., AdminPrincipal]:
    def dependency(principal: AdminPrincipal = Depends(authenticate_admin)) -> AdminPrincipal:
        if _ROLE_ORDER[principal.role] < _ROLE_ORDER[min_role]:
            raise HTTPException(status_code=403, detail=f"Requires role: {min_role}")
        return principal

    return dependency
