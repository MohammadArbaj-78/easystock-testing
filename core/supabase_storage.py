"""
Supabase Storage layer for invoice bill photos.

Uploading a bill's photo is entirely OPTIONAL and best-effort: every
function here returns None on ANY failure (Supabase not configured,
bucket missing, network error, bad file) instead of raising, because a
photo failing to upload must NEVER block saving the medicines or the
agency ledger entry - those are the things that actually matter.

--- Setup required before this works (manual, one-time, in Supabase) ---
1. Supabase Dashboard -> Storage -> New bucket -> name it exactly
   "invoice-bills" (BUCKET_NAME below) -> make it PRIVATE (not public).
2. That's it - no SQL needed for the bucket itself. This module reads
   the photo back via a short-lived SIGNED url (see
   get_invoice_image_url), never a permanent public one.

Moving to a different storage provider later (e.g. Firebase Storage's
5 GB free tier) only ever touches this ONE file - upload_invoice_image
and get_invoice_image_url are the only two functions anything else in
the app calls, and both only ever return/accept a plain path string.
"""

import uuid

BUCKET_NAME = "invoice-bills"

SIGNED_URL_EXPIRY_SECONDS = 300  # 5 minutes


def upload_invoice_image(store_id: int, image_bytes: bytes, content_type: str) -> str:
    """Upload one invoice photo to Supabase Storage.

    Never raises. Returns None on absolutely any failure.

    Args:
        store_id: The current store - used as a folder prefix.
        image_bytes: The raw file bytes exactly as uploaded.
        content_type: MIME type, e.g. "image/jpeg", "application/pdf".

    Returns:
        The Storage path (e.g. "42/7c1e....jpg") on success, or None.
    """
    if not image_bytes:
        return None
    try:
        from core.supabase_client import get_supabase_client

        extension = _extension_for_content_type(content_type)
        path = f"{store_id}/{uuid.uuid4().hex}{extension}"

        get_supabase_client().storage.from_(BUCKET_NAME).upload(
            path,
            image_bytes,
            {"content-type": content_type},
        )
        return path
    except Exception:
        return None


def get_invoice_image_url(image_path: str) -> str:
    """Return a short-lived signed URL for viewing a previously uploaded
    bill photo, or None on any failure.

    Args:
        image_path: The path returned by a previous
            upload_invoice_image() call.

    Returns:
        A signed https URL valid for SIGNED_URL_EXPIRY_SECONDS, or None.
    """
    if not image_path:
        return None
    try:
        from core.supabase_client import get_supabase_client

        response = get_supabase_client().storage.from_(BUCKET_NAME).create_signed_url(
            image_path, SIGNED_URL_EXPIRY_SECONDS
        )
        return response.get("signedURL") or response.get("signedUrl")
    except Exception:
        return None


def _extension_for_content_type(content_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "application/pdf": ".pdf",
    }.get((content_type or "").lower(), "")