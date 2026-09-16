"""
routes/auth.py — Authentication endpoints (NextAuth JWT-based).

The frontend uses NextAuth (Google OAuth + Credentials) for login.
FastAPI validates the NextAuth session cookie on protected routes
via auth_middleware.get_current_user.

Endpoints:
    GET  /auth/me      → return current user from verified JWT
    POST /auth/logout   → clear NextAuth session cookie

--------------------------------------------------------------------------
Fix applied vs. the previous version:
"""
from fastapi import APIRouter, Depends

from auth_middleware import AuthenticatedUser, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
async def auth_me(user: AuthenticatedUser = Depends(get_current_user)):
    """Return the authenticated user's identity from the NextAuth JWT."""
    return {
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
    }


# Cookie names to clear on logout, covering both NextAuth v4 ("next-auth.")
# and Auth.js v5 ("authjs.") naming, plus the non-session cookies NextAuth/
# Auth.js sets alongside the session token. The CSRF cookie uses
# "__Host-" rather than "__Secure-" when secure, confirmed against
# NextAuth.js's cookie configuration reference.
_AUTH_COOKIES_TO_CLEAR = [
    # (base_suffix, secure_prefix)
    ("session-token", "__Secure-"),
    ("callback-url", "__Secure-"),
    ("csrf-token", "__Host-"),
]
_AUTH_COOKIE_PREFIXES = ("next-auth.", "authjs.")  # v4, v5


@router.post("/logout")
async def auth_logout():
    """
    Clear NextAuth/Auth.js session cookies for both v4 and v5 naming
    conventions (see module docstring for why both).
    Note: NextAuth also handles logout client-side via signOut().
    This endpoint is a server-side fallback.
    """
    from fastapi.responses import JSONResponse

    resp = JSONResponse({"status": "logged_out"})

    for auth_prefix in _AUTH_COOKIE_PREFIXES:
        for suffix, secure_prefix in _AUTH_COOKIES_TO_CLEAR:
            # Non-secure (dev / plain HTTP) variant
            resp.delete_cookie(f"{auth_prefix}{suffix}", path="/", samesite="lax")
            # Secure (prod / HTTPS) variant — path and samesite must match
            # the attributes NextAuth/Auth.js used when setting the cookie.
            resp.delete_cookie(
                f"{secure_prefix}{auth_prefix}{suffix}",
                path="/",
                samesite="lax",
                secure=True,
            )

    return resp
