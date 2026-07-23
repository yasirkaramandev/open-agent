from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from urllib.parse import urlparse

YOUTUBE_API_HOSTS = {"www.googleapis.com", "youtube.googleapis.com", "oauth2.googleapis.com"}


def opaque_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def pkce_challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )


def verify_state(expected: str, received: str) -> None:
    if not expected or not received or not hmac.compare_digest(expected, received):
        raise PermissionError("oauth_state_mismatch")


def validate_redirect_uri(expected: str, received: str) -> None:
    expected_url, received_url = urlparse(expected), urlparse(received)
    if (
        expected_url.scheme != received_url.scheme
        or expected_url.netloc != received_url.netloc
        or expected_url.path != received_url.path
        or received_url.query
        or received_url.fragment
    ):
        raise PermissionError("oauth_redirect_uri_mismatch")


def validate_youtube_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in YOUTUBE_API_HOSTS:
        raise PermissionError("ssrf_target_blocked")
    return url


def redact(value: str) -> str:
    lowered = value.lower()
    markers = ("bearer ", "authorization:", "refresh_token", "access_token", "x-api-key")
    if any(marker in lowered for marker in markers):
        return "[REDACTED]"
    return value[:500]


@dataclass(frozen=True, repr=False)
class EncryptedCredential:
    ciphertext: bytes
    key_version: str
    revision: str

    def __repr__(self) -> str:
        return "EncryptedCredential(ciphertext=[REDACTED], key_version=***, revision=***)"
