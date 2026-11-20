"""Who is calling: a bearer token maps to a user, a role and (for a marketplace) a client.

Part A uses Cognito. Locally, each demo user has a token, read from the environment
(DEMO_TOKEN_<USER>, defaults in .env.example). The UI's "acting as" menu sends the chosen user's token.

Deny by default: every route declares the roles it allows with require(...), and a test walks all
routes to check none is left open. Roles:
  marketplace  submits postings and reads its own labels (/v1)
  viewer       reads labels and policies (/ui, /policies)
  editor       also records decisions and edits drafts
  publisher    also publishes and rolls back; never a draft they edited (four eyes)
"""

import os
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


@dataclass(frozen=True)
class User:
    name: str
    role: str
    client_id: str | None = None  # set for marketplace users: they see only their own postings


DEMO_USERS = {
    "marketplace": User("acme-jobs", "marketplace", client_id="acme"),
    "marketplace_b": User("globex-jobs", "marketplace", client_id="globex"),
    "viewer": User("vic", "viewer"),
    "editor": User("eddie", "editor"),
    "publisher_a": User("pat", "publisher"),
    "publisher_b": User("sam", "publisher"),
}

MARKETPLACE = ("marketplace",)
VIEW = ("viewer", "editor", "publisher")
EDIT = ("editor", "publisher")
PUBLISH = ("publisher",)

RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "600"))


def demo_token(key: str) -> str:
    return os.environ.get(f"DEMO_TOKEN_{key.upper()}", f"demo-{key.replace('_', '-')}")


def user_for(token: str) -> User | None:
    for key, user in DEMO_USERS.items():
        if token == demo_token(key):
            return user
    return None


_bearer = HTTPBearer(auto_error=False)


def require(*roles: str):
    """A dependency that lets through only these roles: 401 without a known token, 403 otherwise."""

    async def check(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> User:
        user = user_for(credentials.credentials) if credentials else None
        if user is None:
            raise HTTPException(401, "unauthenticated")
        if user.role not in roles:
            raise HTTPException(403, "forbidden")
        if user.client_id:
            rate_limit(user.client_id)
        return user

    check.roles = roles  # read by the route-walk test
    return check


# Per-client fixed one-minute window, kept in memory: there is one API process locally.
_windows: dict[str, tuple[int, int]] = {}


def rate_limit(client_id: str) -> None:
    minute = int(time.time() // 60)
    start, count = _windows.get(client_id, (minute, 0))
    if start != minute:
        start, count = minute, 0
    if count >= RATE_LIMIT_PER_MINUTE:
        raise HTTPException(429, "rate_limited")
    _windows[client_id] = (start, count + 1)
