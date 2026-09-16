"""
google_token_store.py
======================
Per-user Google OAuth token storage, encrypted at rest, backed by Supabase.

This is the production-grade replacement for the single shared ``token.json``
file. Each end user connects their own Google account (see routes/google_oauth.py)
and their refresh token is stored here, keyed by their verified email, encrypted
with Fernet before it ever touches the database.

Design notes
------------
- Refresh tokens are long-lived credentials. They are NEVER stored in plaintext.
  We encrypt the whole authorized-user JSON blob with a symmetric Fernet key
  supplied via the ``GOOGLE_TOKEN_ENCRYPTION_KEY`` environment variable.
- The table (``jessica_google_tokens``) lives in the same Supabase project as the
  rest of Jessica's data and is protected by service-role-only RLS.
- Access token + expiry are stored alongside the encrypted blob purely as
  non-sensitive metadata for quick "is this connected / when does it expire"
  lookups; the authoritative, refreshable credential lives inside the encrypted
  blob only.

Environment
-----------
- SUPABASE_URL, SUPABASE_KEY        — same as the rest of the app.
- GOOGLE_TOKEN_ENCRYPTION_KEY       — a urlsafe base64 32-byte Fernet key.
      Generate one with:
          python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

_log = logging.getLogger(__name__)

_TABLE = "jessica_google_tokens"

# ── Supabase client (lazy, shared) ────────────────────────────────────────────
_supabase = None


def _get_supabase():
    """Return a cached Supabase client, or None if not configured."""
    global _supabase
    if _supabase is not None:
        return _supabase
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY", "")
    if not (url and key):

        _log.warning(
            "[google_token_store] SUPABASE_URL / SUPABASE_KEY not set — "
            "per-user Google token storage is unavailable."
        )
        return None
    try:
        from supabase import create_client

        _supabase = create_client(url, key)
        return _supabase
    except Exception as exc:  # pragma: no cover - defensive
        _log.error("[google_token_store] Failed to create Supabase client: %s", exc)
        return None


# ── Encryption ────────────────────────────────────────────────────────────────
_fernet: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    """Build (once) the Fernet cipher from GOOGLE_TOKEN_ENCRYPTION_KEY.

    Fails loudly if the key is missing/invalid — we must never silently fall
    back to storing refresh tokens in plaintext.
    """
    global _fernet
    if _fernet is not None:
        return _fernet
    raw = os.getenv("GOOGLE_TOKEN_ENCRYPTION_KEY", "")
    if not raw:
        raise RuntimeError(
            "GOOGLE_TOKEN_ENCRYPTION_KEY is not set. Per-user Google tokens must "
            "be encrypted at rest. Generate a key with:\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"\n"
            "then set it as the GOOGLE_TOKEN_ENCRYPTION_KEY environment variable."
        )
    try:
        _fernet = Fernet(raw.encode() if isinstance(raw, str) else raw)
    except Exception as exc:
        raise RuntimeError(
            f"GOOGLE_TOKEN_ENCRYPTION_KEY is not a valid Fernet key: {exc}. "
            "It must be a urlsafe base64-encoded 32-byte key."
        ) from exc
    return _fernet


def _encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def _decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")


# ── Public API ────────────────────────────────────────────────────────────────

def is_configured() -> bool:
    """True if both Supabase and the encryption key are available."""
    if _get_supabase() is None:
        return False
    try:
        _get_fernet()
        return True
    except RuntimeError:
        return False


def save_user_token(user_email: str, creds_json: str) -> None:
    """Encrypt and upsert a user's authorized-user credentials JSON.

    Args:
        user_email: The verified user email (primary key).
        creds_json: The output of ``Credentials.to_json()`` — the full
            authorized-user blob including the refresh token.
    """
    sb = _get_supabase()
    if sb is None:
        raise RuntimeError("Supabase is not configured — cannot save Google token.")

    try:
        parsed = json.loads(creds_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"creds_json is not valid JSON: {exc}") from exc

    # Non-sensitive metadata for quick lookups (the sensitive parts stay only
    # inside the encrypted blob).
    scopes = parsed.get("scopes") or []
    expiry = parsed.get("expiry")

    row = {
        "user_email": user_email,
        "encrypted_creds": _encrypt(creds_json),
        "expiry": expiry,
        "scopes": scopes,
    }

    sb.table(_TABLE).upsert(row, on_conflict="user_email").execute()
    _log.info("[google_token_store] Saved encrypted Google token for %s", user_email)


def get_user_token(user_email: str) -> Optional[dict]:
    """Return the decrypted authorized-user credentials dict, or None.

    Returns None if the user has not connected Google, if storage is
    unavailable, or if the stored blob cannot be decrypted (e.g. the encryption
    key was rotated).
    """
    sb = _get_supabase()
    if sb is None:
        return None

    try:
        resp = (
            sb.table(_TABLE)
            .select("encrypted_creds")
            .eq("user_email", user_email)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        _log.error("[google_token_store] Read failed for %s: %s", user_email, exc)
        return None

    rows = resp.data or []
    if not rows:
        return None

    enc = rows[0].get("encrypted_creds")
    if not enc:
        return None

    try:
        plaintext = _decrypt(enc)
        return json.loads(plaintext)
    except InvalidToken:
        _log.error(
            "[google_token_store] Could not decrypt token for %s — the "
            "encryption key may have changed. The user must reconnect Google.",
            user_email,
        )
        return None
    except Exception as exc:  # pragma: no cover - defensive
        _log.error("[google_token_store] Corrupt token blob for %s: %s", user_email, exc)
        return None


def delete_user_token(user_email: str) -> None:
    """Remove a user's stored Google token (disconnect)."""
    sb = _get_supabase()
    if sb is None:
        return
    try:
        sb.table(_TABLE).delete().eq("user_email", user_email).execute()
        _log.info("[google_token_store] Deleted Google token for %s", user_email)
    except Exception as exc:
        _log.error("[google_token_store] Delete failed for %s: %s", user_email, exc)


def has_user_token(user_email: str) -> bool:
    """Lightweight check for whether a user has connected Google."""
    sb = _get_supabase()
    if sb is None:
        return False
    try:
        resp = (
            sb.table(_TABLE)
            .select("user_email")
            .eq("user_email", user_email)
            .limit(1)
            .execute()
        )
        return bool(resp.data)
    except Exception:
        return False
