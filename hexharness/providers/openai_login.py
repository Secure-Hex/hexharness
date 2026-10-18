"""Native "Sign in with ChatGPT" OAuth for HexHarness — no Codex CLI required.

HexHarness runs the OAuth 2.0 authorization-code + PKCE flow itself (the same flow the
Codex CLI uses) and stores the resulting tokens in its OWN data dir, not ~/.codex. The
access token is a bearer against the ChatGPT backend Responses endpoint; it is refreshed
in place against auth.openai.com when near expiry.

Endpoints, client_id, scopes and the loopback callback are the published Codex values,
verified against the openai/codex crates and community reimplementations.

Login has two paths:
  * loopback   — spin a one-shot HTTP server on 127.0.0.1:1455, open the browser, capture
                 the redirect automatically. The default on a desktop.
  * manual     — print the URL, read the pasted redirect URL/code from stdin. For headless
                 boxes (SSH, Docker) where no browser/loopback is available.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
from pathlib import Path
from typing import Any

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = f"{_ISSUER}/oauth/authorize"
TOKEN_URL = f"{_ISSUER}/oauth/token"
REDIRECT_URI = "http://localhost:1455/auth/callback"
_CALLBACK_HOST, _CALLBACK_PORT, _CALLBACK_PATH = "127.0.0.1", 1455, "/auth/callback"
SCOPE = "openid profile email offline_access"
_JWT_CLAIM = "https://api.openai.com/auth"  # id_token claim holding chatgpt_account_id
_REFRESH_SKEW = 300  # refresh when the access token expires within this many seconds


# --------------------------------------------------------------------- token store --
def auth_store_path() -> Path:
    override = os.environ.get("HEXHARNESS_OPENAI_AUTH")
    if override:
        return Path(override)
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "hexharness" / "openai_oauth.json"


def _read() -> dict[str, Any]:
    return json.loads(auth_store_path().read_text())


def _write(data: dict[str, Any]) -> None:
    """Write the token store with 0600 perms, atomically."""
    p = auth_store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def is_logged_in() -> bool:
    """True when a HexHarness-owned token store with an access token exists — used by the
    TUI/catalog to decide whether to offer this provider."""
    try:
        return bool(_read().get("access_token"))
    except (OSError, ValueError):
        return False


# --------------------------------------------------------------------- JWT helpers --
def _jwt_claims(jwt: str) -> dict[str, Any]:
    """Decode a JWT payload WITHOUT verifying the signature. These tokens are OpenAI's; we
    only read public claims (exp, account id) to drive refresh — never trusted for auth."""
    try:
        seg = jwt.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        return json.loads(base64.urlsafe_b64decode(seg))
    except (IndexError, ValueError):
        return {}


def _expires_soon(access_token: str) -> bool:
    exp = _jwt_claims(access_token).get("exp")
    if not isinstance(exp, (int, float)):
        return True  # can't tell — refresh to be safe
    return time.time() + _REFRESH_SKEW >= exp


def account_id_from(id_token: str) -> str:
    return _jwt_claims(id_token).get(_JWT_CLAIM, {}).get("chatgpt_account_id", "")


# --------------------------------------------------------------------- PKCE --
def _pkce() -> tuple[str, str]:
    """Return (verifier, S256 challenge), both base64url without padding."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(challenge: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def parse_redirect(value: str) -> dict[str, str]:
    """Extract code/state from a pasted full redirect URL, a 'code#state', or a bare code."""
    value = (value or "").strip()
    if not value:
        return {}
    try:
        q = urllib.parse.urlparse(value).query
        if q:
            qs = urllib.parse.parse_qs(q)
            return {k: qs[k][0] for k in ("code", "state") if k in qs}
    except ValueError:
        pass
    if "#" in value:
        code, state = value.split("#", 1)
        return {"code": code, "state": state}
    return {"code": value}


# --------------------------------------------------------------------- token exchange --
def _store_from_token_response(body: dict[str, Any]) -> dict[str, Any]:
    id_token = body.get("id_token", "")
    return {
        "access_token": body["access_token"],
        "refresh_token": body.get("refresh_token", ""),
        "id_token": id_token,
        "account_id": account_id_from(id_token),
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def exchange_code(code: str, verifier: str) -> dict[str, Any]:
    """Exchange an authorization code for tokens and persist the store. Form-encoded, as
    the OpenAI token endpoint requires for the authorization_code grant."""
    import httpx

    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    store = _store_from_token_response(resp.json())
    _write(store)
    return store


def refresh(store: dict[str, Any]) -> dict[str, Any]:
    """Exchange the refresh token for a fresh access token and persist it."""
    import httpx

    refresh_token = store.get("refresh_token")
    if not refresh_token:
        raise RuntimeError(
            "no refresh_token in the HexHarness OpenAI store; run `hexharness login openai`"
        )
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    body = resp.json()
    store["access_token"] = body["access_token"]
    if body.get("refresh_token"):
        store["refresh_token"] = body["refresh_token"]
    if body.get("id_token"):
        store["id_token"] = body["id_token"]
        store["account_id"] = account_id_from(body["id_token"]) or store.get("account_id", "")
    store["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write(store)
    return store


def load_fresh() -> dict[str, Any]:
    """Load the token store, refreshing the access token first if it is close to expiry."""
    try:
        store = _read()
    except (OSError, ValueError) as e:
        raise RuntimeError(
            f"not logged in to OpenAI ({auth_store_path()}); run `hexharness login openai`"
        ) from e
    token = store.get("access_token")
    if not token:
        raise RuntimeError("OpenAI store has no access_token; run `hexharness login openai`")
    if _expires_soon(token):
        store = refresh(store)
    return store


# --------------------------------------------------------------------- login flows --
_SUCCESS_HTML = (
    "<html><body style='font-family:sans-serif;text-align:center;padding-top:4rem'>"
    "<h2>HexHarness is signed in to OpenAI</h2>"
    "<p>You can close this tab and return to the terminal.</p></body></html>"
)


def _capture_via_loopback(url: str, timeout: float) -> dict[str, str]:
    """Serve one request on 127.0.0.1:1455, return the callback query params."""
    import http.server
    import threading
    import webbrowser

    captured: dict[str, str] = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != _CALLBACK_PATH:
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(parsed.query)
            captured.update({k: v[0] for k, v in qs.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(_SUCCESS_HTML.encode())
            done.set()

        def log_message(self, *a):  # silence the default stderr logging
            pass

    server = http.server.HTTPServer((_CALLBACK_HOST, _CALLBACK_PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        print(f"Opening your browser to sign in. If it doesn't open, visit:\n  {url}")
        webbrowser.open(url)
        if not done.wait(timeout):
            raise RuntimeError(f"login timed out after {int(timeout)}s")
    finally:
        server.shutdown()
        thread.join(timeout=2)
    return captured


def login(*, manual: bool = False, timeout: float = 300.0) -> dict[str, Any]:
    """Run the OAuth login and persist tokens to the HexHarness store. Returns the store.

    manual=True prints the URL and reads the pasted redirect URL/code from stdin (headless).
    Otherwise it captures the redirect automatically via a loopback server on port 1455.
    """
    verifier, challenge = _pkce()
    state = secrets.token_hex(16)
    url = authorize_url(challenge, state)

    if manual:
        print("Open this URL in a browser, sign in, then paste the FULL redirect URL "
              f"(or the code) back here:\n  {url}\n")
        params = parse_redirect(input("redirect URL/code: "))
    else:
        try:
            params = _capture_via_loopback(url, timeout)
        except OSError as e:
            # Port busy (e.g. Codex CLI running) or no loopback — fall back to manual.
            raise RuntimeError(
                f"could not start the local callback server on :{_CALLBACK_PORT} ({e}); "
                "stop anything using that port, or run `hexharness login openai --manual`"
            ) from e

    code = params.get("code")
    returned_state = params.get("state")
    if not code:
        raise RuntimeError("no authorization code received")
    # Only enforce state when the provider returned one (manual bare-code paste has none).
    if returned_state is not None and returned_state != state:
        raise RuntimeError("OAuth state mismatch — aborting (possible CSRF)")
    return exchange_code(code, verifier)


def logout() -> bool:
    """Delete the stored tokens. Returns True if a store existed."""
    try:
        auth_store_path().unlink()
        return True
    except FileNotFoundError:
        return False
