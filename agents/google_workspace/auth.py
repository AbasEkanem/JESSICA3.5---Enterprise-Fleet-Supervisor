"""
google_auth.py

Central authentication helper for Jessica's Google Workspace + Classroom
tool suite. Supports both OAuth 2.0 (installed app flow, for a single user
acting on their own account) and Service Account credentials (for
server-side / domain-wide delegation use cases).

Design notes

- All scopes needed across every module are declared in ALL_SCOPES below.
- Uses narrow scopes per module where practical (e.g. drive.file, calendar.events).
- Automatically auto-detects Service Accounts vs OAuth credentials.json.
- Supports domain-wide delegation subject impersonation.
"""

from __future__ import annotations

import contextvars
import logging
import os
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

import httplib2
import requests as _requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource

_log = logging.getLogger(__name__)

# ── Per-request current user (multi-user mode) ────────────────────────────────
# The chat request handler sets this to the verified user's email at the start
# of every request (see set_current_user_email). Google tool calls made while
# handling that request then resolve THAT user's own stored credentials instead
# of a single shared token.json. A contextvar (not a global) is used so
# concurrent requests each see their own user without cross-talk.
_current_user_email: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "jessica_current_user_email", default=None
)


def set_current_user_email(email: Optional[str]) -> contextvars.Token:
    """Bind the current request's user email. Returns a token for reset()."""
    return _current_user_email.set(email)


def reset_current_user_email(token: contextvars.Token) -> None:
    """Restore the previous current-user binding (call in a finally block)."""
    try:
        _current_user_email.reset(token)
    except Exception:
        pass


def get_current_user_email() -> Optional[str]:
    """Return the current request's bound user email, if any."""
    return _current_user_email.get()


class GoogleNotConnectedError(RuntimeError):
    """Raised when the current user has not connected their Google account.

    Tools should catch this and surface a friendly "connect your Google
    account" message with the connect link, rather than a raw 403/500.
    """


# Network timeout (seconds) applied to token refresh and every API call so a
# slow/hung network can never block a tool call indefinitely.
# Raised 30 → 60s. A large connected/shared Workspace Drive forces Google to
# resolve permissions across every corpus (My Drive + Shared Drives + shared
# items) before a single files().list() returns; on such accounts the old 30s
# socket ceiling was regularly exceeded, surfacing to the drive_agent as a hard
# timeout. 60s gives the initial listing enough headroom while still bounding a
# genuinely hung network. Override via the GOOGLE_API_TIMEOUT env var.
API_TIMEOUT = int(os.getenv("GOOGLE_API_TIMEOUT", "60"))


# In a server/agent context there is no browser and no interactive console, so
# the OAuth consent flow (flow.run_local_server) would block forever. Gate it
# behind an explicit opt-in env flag; default off so tools fail fast instead.
ALLOW_INTERACTIVE_OAUTH = os.getenv("GOOGLE_ALLOW_INTERACTIVE_OAUTH", "0") == "1"

# When true (default), Google credentials are resolved PER USER from the
# encrypted Supabase token store keyed by the current request's user email.
# When false, the app uses the legacy single shared token.json (local/dev).
MULTI_USER_GOOGLE_AUTH = os.getenv("MULTI_USER_GOOGLE_AUTH", "1") == "1"

# Process-wide caches. Building an API client re-fetches the discovery document
# and re-runs the whole credential chain over the network, so we memoize both
# the credentials and the built service clients and reuse them across calls.
#
# NOTE: in multi-user mode these SHARED caches must NOT be used — one user's
# client/creds would leak to another. They are only used in single-user
# (token.json) mode. Per-user clients are cached separately, keyed by email.
_creds_lock = threading.Lock()
_cached_creds: Optional[Any] = None
_service_cache: dict[str, Resource] = {}

# Per-user credential + service caches (multi-user mode). Keyed by user email.
_user_creds_cache: dict[str, Any] = {}
_user_service_cache: dict[tuple[str, str], Resource] = {}



# Scope catalogue
# 

MODULE_SCOPES = {
    "drive": [
        "https://www.googleapis.com/auth/drive",
    ],
    "docs": [
        "https://www.googleapis.com/auth/documents",
    ],
    "sheets": [
        "https://www.googleapis.com/auth/spreadsheets",
    ],
    "slides": [
        "https://www.googleapis.com/auth/presentations",
    ],
    "forms": [
        "https://www.googleapis.com/auth/forms.body",
        "https://www.googleapis.com/auth/forms.responses.readonly",
    ],
    "calendar": [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/calendar.events",
    ],
    "classroom": [
        "https://www.googleapis.com/auth/classroom.courses",
        "https://www.googleapis.com/auth/classroom.coursework.students",
        "https://www.googleapis.com/auth/classroom.announcements",
        "https://www.googleapis.com/auth/classroom.rosters",
        "https://www.googleapis.com/auth/classroom.topics",
    ],
}

ALL_SCOPES: list[str] = sorted({s for scopes in MODULE_SCOPES.values() for s in scopes})

# API name/version pairs used by build()
_SERVICE_VERSIONS = {
    "drive": ("drive", "v3"),
    "docs": ("docs", "v1"),
    "sheets": ("sheets", "v4"),
    "slides": ("slides", "v1"),
    "forms": ("forms", "v1"),
    "calendar": ("calendar", "v3"),
    "classroom": ("classroom", "v1"),
}

# Fixed local port for the OAuth loopback redirect.
# Must match an Authorized redirect URI (http://localhost:<PORT>/)
# registered on the OAuth client in Google Cloud Console.
OAUTH_REDIRECT_PORT = 8080


def get_service_account_credentials(
    key_path: Optional[str] = None,
    scopes: Optional[Iterable[str]] = None,
    subject: Optional[str] = None,
) -> service_account.Credentials:
    """Build credentials from a service account key file.

    `subject` enables domain-wide delegation (impersonating a specific Workspace user).
    """
    key_path = key_path or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "google_service_account.json")
    scopes = list(scopes) if scopes is not None else ALL_SCOPES
    creds = service_account.Credentials.from_service_account_file(key_path, scopes=scopes)
    if subject:
        creds = creds.with_subject(subject)
    return creds


def _timed_request() -> Request:
    """Build a google.auth transport Request whose underlying HTTP session
    enforces API_TIMEOUT, so a hung network cannot block a token refresh forever.
    """
    session = _requests.Session()
    # Wrap Session.request to inject a default timeout when the caller omits one.
    _orig_request = session.request

    def _request_with_timeout(method, url, **kwargs):
        kwargs.setdefault("timeout", API_TIMEOUT)
        return _orig_request(method, url, **kwargs)

    session.request = _request_with_timeout  # type: ignore[assignment]
    return Request(session=session)


def get_credentials(
    scopes: Optional[Iterable[str]] = None,
    client_secret_path: str = "credentials.json",
    token_path: str = "token.json",
    force_refresh: bool = False,
) -> Any:
    """Return valid Google credentials.

    Prioritizes OAuth 2.0 User Flow (token.json / credentials.json) to access
    the user's personal Drive/Docs/Calendar/Classroom resources. Falls back to
    Service Account key if OAuth credentials are not present.

    Credentials are cached process-wide and refreshed in place when expired, so
    repeated tool calls do not re-run the whole auth chain over the network.
    """
    global _cached_creds

    scopes = list(scopes) if scopes is not None else ALL_SCOPES
    client_secret_path = os.getenv("GOOGLE_CREDENTIALS_JSON", client_secret_path)
    token_path = os.getenv("GOOGLE_TOKEN_JSON", token_path)

    with _creds_lock:
        # Fast path: reuse cached creds, refreshing in place if they just expired.
        if _cached_creds is not None and not force_refresh:
            if getattr(_cached_creds, "valid", False):
                return _cached_creds
            if getattr(_cached_creds, "expired", False) and getattr(_cached_creds, "refresh_token", None):
                try:
                    _cached_creds.refresh(_timed_request())
                    if os.path.exists(token_path):
                        with open(token_path, "w", encoding="utf-8") as token_file:
                            token_file.write(_cached_creds.to_json())
                    return _cached_creds
                except Exception as exc:
                    _log.warning("[google_auth] Cached token refresh failed: %s", exc)
                    _cached_creds = None  # fall through to full reload

        # 1. OAuth User Flow (User's personal Google Workspace / Drive / Calendar)
        # Track whether an OAuth token was the *intended* auth method so we can
        # emit an actionable error instead of silently falling back to a service
        # account (which lacks Drive quota and 403s on create — a confusing symptom).
        oauth_refresh_failed = False
        if os.path.exists(token_path) or os.path.exists(client_secret_path):
            creds: Optional[Credentials] = None
            if os.path.exists(token_path):
                try:
                    creds = Credentials.from_authorized_user_file(token_path, scopes)
                except Exception as exc:
                    _log.warning("[google_auth] Failed loading %s: %s", token_path, exc)

            if creds and creds.valid:
                _cached_creds = creds
                return creds

            if creds and creds.expired and creds.refresh_token:
                _log.info("[google_auth] Refreshing expired OAuth token...")
                try:
                    creds.refresh(_timed_request())
                    with open(token_path, "w", encoding="utf-8") as token_file:
                        token_file.write(creds.to_json())
                    _cached_creds = creds
                    return creds
                except Exception as exc:
                    oauth_refresh_failed = True
                    _log.warning("[google_auth] OAuth token refresh failed: %s", exc)


            # No valid/refreshable user token. The interactive consent flow opens
            # a browser and blocks forever in a headless server context, so only
            # run it when explicitly opted in (e.g. local first-time setup).
            if os.path.exists(client_secret_path) and ALLOW_INTERACTIVE_OAUTH:
                _log.info("[google_auth] Launching Desktop OAuth consent flow for %s...", client_secret_path)
                flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, scopes)
                creds = flow.run_local_server(port=0, prompt="consent")
                with open(token_path, "w", encoding="utf-8") as token_file:
                    token_file.write(creds.to_json())
                _cached_creds = creds
                return creds

        # If the user's OAuth token existed but its refresh failed (revoked /
        # expired refresh token), do NOT silently fall back to a service account.
        # A bare service account has no personal-Drive storage quota, so any
        # create call (Slides/Docs/Sheets) will fail with a misleading
        # "403 The caller does not have permission". Fail loudly with the real
        # cause and the exact remediation instead.
        if oauth_refresh_failed:
            raise RuntimeError(
                f"[google_auth] The OAuth token ({token_path}) has expired or been "
                "revoked and could not be refreshed (Google returned 'invalid_grant'). "
                "Re-authorize to mint a fresh token.json:\n"
                "  set GOOGLE_ALLOW_INTERACTIVE_OAUTH=1 && python google_auth.py\n"
                "(A service account key is present but is intentionally NOT used here: "
                "it has no personal-Drive quota and would only produce a misleading "
                "'403 caller does not have permission' on create.)"
            )

        # 2. Fall back to Service Account key if no OAuth user credentials exist
        sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "google_service_account.json")
        if Path(sa_path).exists():
            _log.info("[google_auth] Using Service Account key fallback: %s", sa_path)
            _cached_creds = get_service_account_credentials(sa_path, scopes=scopes)
            return _cached_creds


        # No usable credentials. Fail fast with an actionable message instead of
        # hanging on an interactive flow that can never complete server-side.
        raise RuntimeError(
            "[google_auth] No valid Google credentials available. The OAuth token "
            f"({token_path}) is missing/expired and could not be refreshed, and no "
            "service account key was found. Re-run the OAuth consent flow locally "
            "(python google_auth.py, with GOOGLE_ALLOW_INTERACTIVE_OAUTH=1) to mint "
            "a fresh token.json, or configure a service account."
        )



def get_user_credentials(user_email: str, force_refresh: bool = False) -> Any:
    """Return valid, refreshed Google credentials for a specific user.

    Loads the user's encrypted authorized-user token from the Supabase token
    store, refreshes it in place if expired (persisting the refreshed token
    back), and caches the live credential object per user for the process.

    Raises:
        GoogleNotConnectedError: if the user has no stored token, or their
            refresh token is revoked/expired and cannot be refreshed. In both
            cases the remedy is the same: the user must (re)connect Google.
    """
    # Import lazily so google_auth has no hard dependency on the store in
    # single-user/local mode (and to avoid a circular import at module load).
    from .token_store import get_user_token, save_user_token

    with _creds_lock:
        cached = _user_creds_cache.get(user_email)
    if cached is not None and not force_refresh and getattr(cached, "valid", False):
        return cached

    token_dict = get_user_token(user_email)
    if not token_dict:
        raise GoogleNotConnectedError(
            f"User {user_email} has not connected a Google account."
        )

    try:
        creds = Credentials.from_authorized_user_info(token_dict, ALL_SCOPES)
    except Exception as exc:
        raise GoogleNotConnectedError(
            f"Stored Google token for {user_email} is unreadable ({exc}); "
            "the user must reconnect Google."
        ) from exc

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(_timed_request())
                # Persist the refreshed access token (refresh token is retained).
                save_user_token(user_email, creds.to_json())
            except Exception as exc:
                _log.warning(
                    "[google_auth] Per-user token refresh failed for %s: %s",
                    user_email,
                    exc,
                )
                raise GoogleNotConnectedError(
                    f"Google access for {user_email} has expired or been revoked "
                    "and could not be refreshed. The user must reconnect Google."
                ) from exc
        else:
            raise GoogleNotConnectedError(
                f"Google credentials for {user_email} are invalid and have no "
                "refresh token. The user must reconnect Google."
            )

    with _creds_lock:
        _user_creds_cache[user_email] = creds
    return creds


def invalidate_user_cache(user_email: str) -> None:
    """Drop cached creds/services for a user (call on disconnect / reconnect)."""
    with _creds_lock:
        _user_creds_cache.pop(user_email, None)
        for key in [k for k in _user_service_cache if k[0] == user_email]:
            _user_service_cache.pop(key, None)


def _build_service(api: str, credentials: Any) -> Resource:
    """Construct a googleapiclient Resource with a network timeout on every
    request and static discovery (no live discovery-document fetch)."""

    name, version = _SERVICE_VERSIONS[api]
    # AuthorizedHttp wraps an httplib2.Http (which carries the socket timeout)
    # and injects/refreshes the OAuth credentials on each request.
    authed_http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=API_TIMEOUT))
    return build(
        name,
        version,
        http=authed_http,
        cache_discovery=False,
        static_discovery=True,
    )


def get_service(
    api: str,
    credentials: Optional[Any] = None,
    scopes: Optional[Iterable[str]] = None,
) -> Resource:
    """Build (or reuse) a ready-to-use API client Resource object.

    Supported APIs: drive, docs, sheets, slides, forms, calendar, classroom.

    Clients are cached process-wide keyed by API name. The cached client holds
    a reference to the shared, auto-refreshing credentials, so a single build
    serves every subsequent tool call without re-fetching discovery documents.
    """
    if api not in _SERVICE_VERSIONS:
        raise ValueError(f"Unknown api '{api}'. Expected one of {list(_SERVICE_VERSIONS)}")

    # Caller supplied explicit credentials — don't cache; build a fresh client.
    if credentials is not None:
        return _build_service(api, credentials)

    # ── Multi-user mode: resolve THIS request's user from the contextvar and
    # build a client bound to their own stored credentials. Clients are cached
    # per (user, api) so concurrent users never share a client. ──────────────
    if MULTI_USER_GOOGLE_AUTH:
        user_email = get_current_user_email()
        if user_email:
            cache_key = (user_email, api)
            with _creds_lock:
                cached = _user_service_cache.get(cache_key)
            if cached is not None:
                return cached
            user_creds = get_user_credentials(user_email)
            service = _build_service(api, user_creds)
            with _creds_lock:
                _user_service_cache[cache_key] = service
            return service
        # No bound user in a multi-user deployment: fail clearly rather than
        # silently acting as some shared identity.
        raise GoogleNotConnectedError(
            "No authenticated user is bound to this request, so no Google "
            "account can be used. (MULTI_USER_GOOGLE_AUTH is enabled.)"
        )

    # ── Single-user / local mode: shared token.json client, cached by api. ───
    with _creds_lock:
        cached = _service_cache.get(api)
    if cached is not None:
        return cached

    module_scopes = scopes if scopes is not None else ALL_SCOPES
    credentials = get_credentials(scopes=module_scopes)
    service = _build_service(api, credentials)
    with _creds_lock:
        _service_cache[api] = service
    return service




# Compatibility alias for tool functions calling get_google_service("drive", "v3")
def get_google_service(service_name: str, version: str = "") -> Resource:
    """Convenience lookup supporting both get_service('drive') and legacy get_google_service('drive', 'v3')."""
    return get_service(service_name)


def connect_user_via_browser(user_email: str, client_secret_path: Optional[str] = None) -> None:
    """Run the interactive OAuth consent flow for ONE user and store their
    encrypted token in Supabase (the per-user, multi-user model).

    This is the local/admin way to mint a per-user token without going through
    the web /google/connect endpoint. It opens a browser, has the user grant
    consent, then writes the resulting refresh token — encrypted — into the
    Supabase token store keyed by ``user_email``.

    Requires GOOGLE_TOKEN_ENCRYPTION_KEY + SUPABASE_URL/KEY to be configured.
    """
    from .token_store import is_configured, save_user_token

    if not is_configured():
        raise RuntimeError(
            "Per-user token storage is not configured. Set SUPABASE_URL, "
            "SUPABASE_KEY and GOOGLE_TOKEN_ENCRYPTION_KEY before running --connect."
        )

    client_secret_path = client_secret_path or os.getenv("GOOGLE_CREDENTIALS_JSON", "credentials.json")
    if not os.path.exists(client_secret_path):
        raise RuntimeError(
            f"OAuth client secrets file not found: {client_secret_path}. "
            "Set GOOGLE_CREDENTIALS_JSON to your OAuth client's credentials.json."
        )

    # access_type=offline + prompt=consent guarantees a refresh token is issued.
    flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, ALL_SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    if not getattr(creds, "refresh_token", None):
        raise RuntimeError(
            "No refresh token was returned by Google. Re-run and ensure you fully "
            "grant consent (the flow uses prompt=consent to force this)."
        )

    save_user_token(user_email, creds.to_json())
    invalidate_user_cache(user_email)
    print(f"[google_auth] SUCCESS! Encrypted Google token stored for {user_email}.")


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description="Jessica Google OAuth helper. With --connect, runs the "
        "browser consent flow for a specific user and stores their encrypted "
        "token in Supabase (multi-user mode). With no args, mints the legacy "
        "single-user token.json."
    )
    parser.add_argument(
        "--connect",
        metavar="EMAIL",
        help="Connect a specific user's Google account (per-user, encrypted "
        "Supabase storage). Example: python google_auth.py --connect you@example.com",
    )
    args = parser.parse_args()

    if args.connect:
        print(f"[google_auth] Launching browser consent flow for {args.connect}...")
        connect_user_via_browser(args.connect)
    else:
        # Legacy single-user path: mint/refresh token.json. Requires
        # GOOGLE_ALLOW_INTERACTIVE_OAUTH=1 for the browser flow to run.
        print("[google_auth] Starting Google OAuth authorization (single-user token.json)...")
        get_credentials()
        print("[google_auth] SUCCESS! OAuth Token authorized and saved to token.json.")

