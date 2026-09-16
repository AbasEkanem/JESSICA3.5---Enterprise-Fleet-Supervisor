"""
routes/google_oauth.py — Per-user Google Workspace connect flow.

This is the OAuth 2.0 web flow that lets each authenticated Jessica user
connect their OWN Google account so tools (Slides/Docs/Drive/Calendar/etc.)
act on their behalf. The resulting refresh token is stored encrypted in
Supabase (see google_token_store.py), keyed by the user's verified email.

Endpoints
---------
GET  /google/status      → is the current user connected? (+ metadata)
GET  /google/connect      → 302 redirect to Google's consent screen
GET  /google/callback     → Google redirects here with ?code&state; we exchange
                            the code for tokens and persist them, then bounce the
                            user back to the frontend.
POST /google/disconnect   → delete the current user's stored Google token

Security
--------
- The OAuth `state` parameter is an HMAC-signed, time-limited token bound to the
  requesting user's email. On callback we verify the signature and expiry before
  trusting the identity, which prevents login-CSRF / token-swap attacks.
- `access_type=offline` + `prompt=consent` ensures Google always returns a
  refresh token (required for long-lived, unattended access).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from fastapi.responses import JSONResponse, RedirectResponse

from auth_middleware import AuthenticatedUser, get_current_user
from config import BACKEND_URL, SESSION_SECRET
from agents.google_workspace.auth import ALL_SCOPES, invalidate_user_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/google", tags=["google-oauth"])

# Where to send the user after a successful/failed connect (frontend origin).
_FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# The redirect URI must be registered EXACTLY in the Google Cloud Console OAuth
# client's "Authorized redirect URIs".
_REDIRECT_URI = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", f"{BACKEND_URL}/google/callback")

_CLIENT_SECRETS_PATH = os.getenv("GOOGLE_CREDENTIALS_JSON", "credentials.json")

# Signed-state lifetime (seconds). The user must complete consent within this
# window; a stale/replayed state is rejected.
_STATE_TTL_S = 600


# ── Signed state helpers (CSRF protection) ────────────────────────────────────

def _sign_state(email: str) -> str:
    """Create an HMAC-signed, timestamped state bound to the user's email."""
    issued = str(int(time.time()))
    payload = f"{email}:{issued}"
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def _verify_state(state: str) -> str:
    """Verify a signed state and return the bound email, or raise HTTPException."""
    import urllib.parse
    raw_state = urllib.parse.unquote(state)
    try:
        email, issued, sig = raw_state.rsplit(":", 2)
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed OAuth state")

    payload = f"{email}:{issued}"
    expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=400, detail="Invalid OAuth state signature")

    try:
        if time.time() - int(issued) > _STATE_TTL_S:
            raise HTTPException(status_code=400, detail="OAuth state expired; please retry")
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed OAuth state timestamp")

    return email


def _build_flow(state: str | None = None):
    """Construct a google-auth-oauthlib Flow from the client secrets file."""
    # Imported here so a missing optional dep doesn't break app import.
    from google_auth_oauthlib.flow import Flow

    if not os.path.exists(_CLIENT_SECRETS_PATH):
        raise HTTPException(
            status_code=500,
            detail=(
                "Google OAuth client secrets file not found. Set "
                "GOOGLE_CREDENTIALS_JSON to your OAuth client's credentials.json."
            ),
        )

    flow = Flow.from_client_secrets_file(
        _CLIENT_SECRETS_PATH,
        scopes=ALL_SCOPES,
        redirect_uri=_REDIRECT_URI,
        state=state,
        # PKCE is stateful: the Flow auto-generates a random code_verifier when
        # building the consent URL in /connect, but /callback constructs a brand
        # new Flow that has no memory of that verifier — so Google rejects the
        # exchange with "invalid_grant: Missing code verifier". We use a
        # confidential "web" client (with a client_secret), so PKCE isn't
        # required; disable the auto code_verifier to keep the flow stateless.
        autogenerate_code_verifier=False,
    )
    return flow



# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
async def google_status(user: AuthenticatedUser = Depends(get_current_user)):
    """Report whether the current user has connected their Google account."""
    from agents.google_workspace.token_store import has_user_token, is_configured

    if not is_configured():
        return {
            "connected": False,
            "available": False,
            "detail": (
                "Per-user Google connect is not configured on the server "
                "(missing Supabase or GOOGLE_TOKEN_ENCRYPTION_KEY)."
            ),
        }
    return {
        "connected": has_user_token(user.email),
        "available": True,
    }


@router.get("/connect")
async def google_connect(user: AuthenticatedUser = Depends(get_current_user)):
    """Begin the OAuth flow — redirect the user to Google's consent screen."""
    signed_state = _sign_state(user.email)
    flow = _build_flow(state=signed_state)
    auth_url, _ = flow.authorization_url(
        access_type="offline",       # request a refresh token
        include_granted_scopes="true",
        prompt="consent",            # force refresh-token issuance every time
        state=signed_state,          # preserve signed state in authorization_url call
    )
    return RedirectResponse(auth_url, status_code=302)


@router.get("/callback")
async def google_callback(request: Request):
    """Handle Google's redirect: exchange the auth code and persist the token.

    This route is hit by Google's servers redirecting the user's browser, so it
    is NOT behind get_current_user — identity is instead proven by the signed
    `state` parameter we issued in /connect.
    """
    from agents.google_workspace.token_store import save_user_token

    error = request.query_params.get("error")
    if error:
        logger.warning("[google_oauth] Consent denied/error: %s", error)
        return RedirectResponse(
            f"{_FRONTEND_URL}/?google_connected=0&reason={error}", status_code=302
        )

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    # Verify the signed state → the email that initiated the connect.
    email = _verify_state(state)

    flow = _build_flow(state=state)
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        logger.error("[google_oauth] Token exchange failed for %s: %s", email, exc)
        return RedirectResponse(
            f"{_FRONTEND_URL}/?google_connected=0&reason=exchange_failed", status_code=302
        )

    creds = flow.credentials
    if not creds.refresh_token:
        # Without a refresh token we can't maintain long-lived access. This
        # happens if the user previously granted consent and Google skipped
        # re-issuing one; prompt=consent in /connect should prevent it.
        logger.warning("[google_oauth] No refresh token returned for %s", email)
        return RedirectResponse(
            f"{_FRONTEND_URL}/?google_connected=0&reason=no_refresh_token", status_code=302
        )

    try:
        save_user_token(email, creds.to_json())
        invalidate_user_cache(email)  # ensure the new token is picked up
    except Exception as exc:
        logger.error("[google_oauth] Failed to persist token for %s: %s", email, exc)
        return RedirectResponse(
            f"{_FRONTEND_URL}/?google_connected=0&reason=store_failed", status_code=302
        )

    logger.info("[google_oauth] Google account connected for %s", email)
    return RedirectResponse(f"{_FRONTEND_URL}/?google_connected=1", status_code=302)


@router.post("/disconnect")
async def google_disconnect(user: AuthenticatedUser = Depends(get_current_user)):
    """Delete the current user's stored Google token."""
    from agents.google_workspace.token_store import delete_user_token

    delete_user_token(user.email)
    invalidate_user_cache(user.email)
    return JSONResponse({"status": "disconnected"})
