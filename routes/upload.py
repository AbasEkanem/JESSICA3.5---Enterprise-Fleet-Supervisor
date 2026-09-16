"""
routes/upload.py — Secure, user-scoped file upload endpoint.
Enforces 20 MB cap, MIME allowlist via python-magic, and per-user directories.

"""
import os
import uuid

try:
    import magic
except ImportError as exc:
    raise ImportError(
        "python-magic failed to import -- this almost always means the "
        "system libmagic library is missing (python-magic is a thin "
        "wrapper around it, not a bundled pip package). "
        "Debian/Ubuntu (most Docker base images): apt-get install -y libmagic1. "
        "Alpine: apk add file. "
        f"Original error: {exc}"
    ) from exc

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from config import MAX_UPLOAD_BYTES
from auth_middleware import AuthenticatedUser, get_current_user, safe_user_id

router = APIRouter(tags=["upload"])

ALLOWED_MIME_TYPES = {
    "application/pdf", "text/plain", "text/csv",
    "application/json", "image/png", "image/jpeg", "image/webp",
}
_MIME_TO_EXT = {
    "application/pdf": ".pdf", "text/plain": ".txt", "text/csv": ".csv",
    "application/json": ".json", "image/png": ".png",
    "image/jpeg": ".jpg", "image/webp": ".webp",
}

UPLOAD_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "uploads")

_READ_CHUNK_BYTES = 1024 * 1024  # 1 MB


@router.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        # Bounded chunked read -- aborts as soon as the cap is exceeded
        # instead of buffering an arbitrarily large body first. See fix #1.
        buf = bytearray()
        while True:
            chunk = await file.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            buf.extend(chunk)
            if len(buf) > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                )
        contents = bytes(buf)

        detected_mime = magic.from_buffer(contents, mime=True)
        if detected_mime not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=415,
                detail=f"File type '{detected_mime}' is not permitted.",
            )

        # Extension derived from the VERIFIED MIME type, never from the
        # client-supplied filename. See fix #2.
        safe_ext = _MIME_TO_EXT[detected_mime]

        # User-scoped upload directory
        uid = safe_user_id(user)
        user_upload_dir = os.path.join(UPLOAD_ROOT, uid)
        os.makedirs(user_upload_dir, exist_ok=True)

        filename = f"{uuid.uuid4().hex}{safe_ext}"
        file_path = os.path.join(user_upload_dir, filename)

        # Path-traversal guard (see module docstring: provably unreachable
        # given fix #2, kept as cheap defense-in-depth).
        resolved     = os.path.realpath(file_path)
        resolved_dir = os.path.realpath(user_upload_dir)
        if not resolved.startswith(resolved_dir + os.sep):
            raise HTTPException(status_code=400, detail="Invalid file path.")

        with open(file_path, "wb") as out:
            out.write(contents)

        return {"filename": filename, "path": file_path}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))