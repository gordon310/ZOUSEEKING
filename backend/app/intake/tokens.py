"""Hash-only bearer tokens for anonymous intake sessions."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from secrets import token_urlsafe


@dataclass(frozen=True)
class SessionToken:
    raw: str
    digest: str


def hash_session_token(raw: str) -> str:
    if not raw:
        raise ValueError("session token is required")
    return sha256(raw.encode("utf-8")).hexdigest()


def new_session_token() -> SessionToken:
    raw = token_urlsafe(32)
    return SessionToken(raw=raw, digest=hash_session_token(raw))


def verify_session_token(raw: str, expected_digest: str) -> bool:
    if not raw or not expected_digest:
        return False
    return compare_digest(hash_session_token(raw), expected_digest)
