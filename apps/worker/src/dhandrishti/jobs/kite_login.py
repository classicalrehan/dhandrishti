"""Daily Kite Connect login (manual, as Zerodha requires).

    KITE_API_KEY=... KITE_API_SECRET=... uv run python -m dhandrishti.jobs.kite_login

1. Prints (and opens) the Kite login page; you log in with your Zerodha credentials + 2FA.
2. Kite redirects to http://127.0.0.1:<port>/kite/callback (register exactly this URL as the
   app's Redirect URL in https://developers.kite.trade); this script catches the request_token.
3. The token is exchanged for an access token, saved to ~/.config/dhandrishti/kite_session.json
   (mode 600). It expires at 6 AM the next day.

The API secret is read from the environment (or prompted for) and never written anywhere.
Fallback when the redirect cannot reach this machine: --request-token <token from the URL>.
"""

import argparse
import getpass
import os
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, quote, urlparse

from ..providers.kite.client import KiteClient, KiteError
from ..providers.kite.session import DEFAULT_SESSION_FILE, load_session, login_url, save_session

PAGE = (b"<html><body style='font-family:system-ui;background:#070b14;color:#e8edf5;padding:3rem'>"
        b"<h2>DhanDrishti: Kite login received</h2><p>You can close this tab and return to the terminal.</p>"
        b"</body></html>")


def wait_for_request_token(port: int, state: str, timeout: float = 300.0) -> str:
    """Serve /kite/callback on 127.0.0.1 until Kite redirects there with our state."""
    result: dict[str, str] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path != "/kite/callback":
                self.send_response(404)
                self.end_headers()
                return
            if q.get("state") != state:
                result["error"] = "state mismatch (ignored a redirect that did not come from this login)"
            elif q.get("status") != "success" or "request_token" not in q:
                result["error"] = f"login not successful: {q.get('status', 'unknown')}"
            else:
                result["request_token"] = q["request_token"]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE)
            done.set()

        def log_message(self, *args):  # keep the request_token out of the terminal log
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if not done.wait(timeout):
            raise TimeoutError("No redirect from Kite within 5 minutes. Use --request-token instead.")
    finally:
        server.shutdown()
    if "error" in result:
        raise RuntimeError(result["error"])
    return result["request_token"]


def remembered_api_key() -> str | None:
    """The API key is an app identifier, not a secret; reuse it from the last saved session."""
    try:
        return load_session().api_key
    except (FileNotFoundError, ValueError, TypeError, KeyError):
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=int(os.environ.get("KITE_REDIRECT_PORT", 5010)))
    ap.add_argument("--request-token", help="skip the local redirect and use this token")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)

    api_key = os.environ.get("KITE_API_KEY") or remembered_api_key()
    if api_key:
        print(f"Using Kite API key {api_key[:4]}…{api_key[-2:]} (from {'KITE_API_KEY' if os.environ.get('KITE_API_KEY') else 'your last login'})")
    else:
        api_key = input("Kite API key: ").strip()
    api_secret = os.environ.get("KITE_API_SECRET") or getpass.getpass("Kite API secret (hidden): ").strip()
    if not api_key or not api_secret:
        print("API key and secret are required (https://developers.kite.trade).", file=sys.stderr)
        return 2

    request_token = args.request_token
    if not request_token:
        state = secrets.token_urlsafe(16)
        url = f"{login_url(api_key)}&redirect_params={quote(f'state={state}')}"
        print(f"Redirect URL registered in your Kite app must be: http://127.0.0.1:{args.port}/kite/callback")
        print(f"Log in here:\n  {url}\n")
        if not args.no_browser:
            webbrowser.open(url)
        request_token = wait_for_request_token(args.port, state)

    client = KiteClient(api_key)
    try:
        session = client.exchange_request_token(request_token, api_secret)
    except KiteError as exc:
        print(f"Login failed: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()
    path = save_session(session)
    print(f"Logged in as {session.user_id or 'unknown'}. Session saved to {path} (valid until 6 AM tomorrow).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
