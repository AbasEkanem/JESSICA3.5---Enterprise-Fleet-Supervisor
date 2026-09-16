"""
auth_middleware.py — NextAuth JWT verification for FastAPI.

Decrypts the NextAuth JWE session token from the request cookie
and returns an AuthenticatedUser. All protected routes use
get_current_user as a FastAPI dependency.

Key derivation matches NextAuth.js exactly:
  HKDF(SHA-256, secret, salt=zeros, info="NextAuth.js Generated Encryption Key", length=32)
  Algorithm: dir + A256GCM

Cookie names checked:
  - next-auth.session-token            (HTTP / development)
  - __Secure-next-auth.session-token   (HTTPS / production)
"""

import base64
import json
import logging
from dataclasses import dataclass
from typing import Optional

from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from fastapi import HTTPException, Request
from jwcrypto import jwe, jwk

from config import NEXTAUTH_SECRET

logger = logging.getLogger(__name__)


# ── Data model ──────────────────────────────────────────────────────────────

@dataclass
class AuthenticatedUser:
    """Verified user identity extracted from the NextAuth JWT."""
    email: str
    name: str
    picture: str = ""


# ── Key derivation (runs once at import) ────────────────────────────────────

def _derive_encryption_key(secret: str) -> bytes:
    """
    Derive the JWE decryption key from NEXTAUTH_SECRET.
    Matches NextAuth.js: hkdf("sha256", secret, "", info, 32)
    A256GCM requires a 32-byte (256-bit) key.
    """
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,   # None → HashLen zeros per RFC 5869 (matches Node's empty string)
        info=b"NextAuth.js Generated Encryption Key",
    )
    return hkdf.derive(secret.encode("utf-8"))


_ENCRYPTION_KEY: Optional[jwk.JWK] = None


def _get_key() -> jwk.JWK:
    """Lazily build and cache the JWK from the derived key bytes."""
    global _ENCRYPTION_KEY
    if _ENCRYPTION_KEY is None:
        if not NEXTAUTH_SECRET:
            raise RuntimeError(
                "NEXTAUTH_SECRET is not set — cannot verify sessions"
            )
        raw = _derive_encryption_key(NEXTAUTH_SECRET)
        k_b64 = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
        _ENCRYPTION_KEY = jwk.JWK(kty="oct", k=k_b64)
    return _ENCRYPTION_KEY


# ── Token decryption 

def _decrypt_token(token: str) -> dict:
    """Decrypt a NextAuth JWE compact-serialized token → payload dict."""
    try:
        key = _get_key()
        token_obj = jwe.JWE()
        token_obj.deserialize(token)
        token_obj.decrypt(key)
        return json.loads(token_obj.payload)
    except Exception as e:
        logger.warning("[AUTH] Token decryption failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired session")


# ── FastAPI dependency

async def get_current_user(request: Request) -> AuthenticatedUser:
    """
    FastAPI dependency — extract and verify the NextAuth session cookie.

    Usage in any route:
        from auth_middleware import get_current_user, AuthenticatedUser
        from fastapi import Depends

        @router.post("/my-route")
        async def my_route(user: AuthenticatedUser = Depends(get_current_user)):
            print(user.email, user.name)
    """
    # NextAuth uses different cookie names for HTTP vs HTTPS
    token = (
        request.cookies.get("next-auth.session-token")
        or request.cookies.get("__Secure-next-auth.session-token")
    )

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = _decrypt_token(token)

    email = payload.get("email")
    if not email:
        raise HTTPException(
            status_code=401,
            detail="Invalid session: missing email claim",
        )

    return AuthenticatedUser(
        email=email,
        name=payload.get("name", email.split("@")[0]),
        picture=payload.get("picture", ""),
    )


# ── Utility ──────────────────────────────────────────────────────────────────

def safe_user_id(user: AuthenticatedUser) -> str:
    """Sanitize email into a safe string for use as keys/paths."""
    return user.email.replace(".", "_").replace("@", "_")


def namespace_thread(user: AuthenticatedUser, thread_id: str) -> str:
    """
    Prefix a thread_id with the user's email to enforce ownership.
    Users can only access threads in their own namespace by construction.
    Idempotent: if thread_id is already prefixed, return it as-is.
    """
    prefix = f"{user.email}::"
    if thread_id.startswith(prefix):
        return thread_id
    return f"{prefix}{thread_id}"
