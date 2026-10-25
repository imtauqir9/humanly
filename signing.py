"""
Expiring download links, shared by the web app and the pipeline.

/dl/<exp>/<sig>/<path> serves one file under output/ without a login: the
signature is an HMAC over the expiry and the path. The pipeline signs links
too (it hands Tavus the avatar's narration this way), so both must derive the
same key: SECRET_KEY when set, otherwise one derived from APP_PASSWORD.
"""

import base64
import hashlib
import hmac
import os
import time


def secret_key() -> str:
    configured = os.environ.get("SECRET_KEY", "")
    return configured or hashlib.sha256(
        ("humanly-session-v1:" + os.environ.get("APP_PASSWORD", "")).encode()).hexdigest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def download_sig(path: str, exp: int, key: str | None = None) -> str:
    msg = f"{exp}|{path}".encode()
    return _b64(hmac.new((key or secret_key()).encode(), msg, hashlib.sha256).digest())


def signed_url(path: str, base_url: str, ttl: int, key: str | None = None) -> str:
    exp = int(time.time()) + ttl
    return f"{base_url.rstrip('/')}/dl/{exp}/{download_sig(path, exp, key)}/{path}"
