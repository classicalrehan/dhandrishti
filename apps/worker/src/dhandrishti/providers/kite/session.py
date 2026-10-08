"""Kite Connect login and session storage.

Flow (https://kite.trade/docs/connect/v3/user/):
  1. Open https://kite.zerodha.com/connect/login?v=3&api_key=<key> and log in manually.
  2. Kite redirects to the app's registered redirect URL with ?request_token=...&status=success
  3. POST /session/token with checksum = SHA-256(api_key + request_token + api_secret)
  4. The access token is valid until 6 AM the next day. Log in again each day.

The api_secret is only used in step 3 and is never stored. The session (access token) is saved
to a user-only file outside the repository.
"""

import hashlib
import json
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path

LOGIN_URL = "https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
DEFAULT_SESSION_FILE = Path(os.environ.get(
    "DD_KITE_SESSION_FILE", Path.home() / ".config" / "dhandrishti" / "kite_session.json"))


@dataclass(frozen=True)
class KiteSession:
    api_key: str
    access_token: str
    user_id: str | None
    login_time: str | None


def login_url(api_key: str) -> str:
    return LOGIN_URL.format(api_key=api_key)


def checksum(api_key: str, request_token: str, api_secret: str) -> str:
    return hashlib.sha256(f"{api_key}{request_token}{api_secret}".encode()).hexdigest()


def save_session(session: KiteSession, path: Path = DEFAULT_SESSION_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create with 0600 from the start so the token is never world-readable, even briefly.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(asdict(session), f)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return path


def load_session(path: Path = DEFAULT_SESSION_FILE) -> KiteSession:
    if not path.exists():
        raise FileNotFoundError(f"No Kite session at {path}. Run `pnpm kite:login` first.")
    return KiteSession(**json.loads(path.read_text(encoding="utf-8")))
