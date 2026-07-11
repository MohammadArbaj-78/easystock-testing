"""
File upload utilities for EasyStock.

Lives in utils/ (not modules/invoice_scan/) because these functions
will be reused by the future OCR pipeline, AI extractor, and any other
module that accepts file uploads. Same reason validators.py lives here:
utilities with no module-specific business logic belong in the shared
layer, not inside a feature module.

All functions are pure or near-pure: given inputs, return a result or
raise a specific exception. Nothing here touches Streamlit session state
or renders UI.
"""

import io
import os
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image

from config.settings import (
    UPLOADS_DIR,
    UPLOADS_MAX_BYTES,
    ALLOWED_UPLOAD_EXTENSIONS,
    PDF_PREVIEW_DPI,
)
from core.exceptions import ValidationError


# ---------------------------------------------------------------------------
# Store-scoped upload folder
# ---------------------------------------------------------------------------

def get_store_upload_dir(store_id: int) -> Path:
    """Return the upload directory for a specific store, creating it if
    it does not exist.

    Each store gets its own subdirectory under UPLOADS_DIR:
        data/uploads/{store_id}/

    Isolation is enforced structurally: no code in this file ever writes
    to a path that doesn't include the requesting store's own ID, so
    there is no code path through which one store's file can land in
    another store's folder - even if a bug in the calling code passes a
    wrong store_id, the worst outcome is writing to that store's own
    folder, not reading or overwriting another store's files.

    Args:
        store_id: The currently logged-in store's ID.

    Returns:
        A Path object pointing to the store's upload directory.
    """
    store_dir = Path(UPLOADS_DIR) / str(store_id)
    store_dir.mkdir(parents=True, exist_ok=True)
    return store_dir


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_upload(file_obj) -> None:
    """Validate an uploaded file object against extension and size rules.

    Validation order matters for user experience: extension is checked
    first (cheapest, no I/O, gives the clearest error for the most
    common mistake) then size (requires reading the byte count). Content-
    type sniffing is deliberately not performed here - invoice images
    from a cheap scanner or a photo from a phone sometimes have wrong or
    missing MIME headers. Extension + size is the right tradeoff for this
    use case.

    Args:
        file_obj: A Streamlit UploadedFile object (or anything with
            .name: str and .size: int attributes).

    Raises:
        ValidationError: If the file fails any validation rule, with a
            human-readable message suitable for st.error().
    """
    if file_obj is None:
        raise ValidationError("No file was uploaded.")

    ext = Path(file_obj.name).suffix.lstrip(".").lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS)).upper()
        raise ValidationError(
            f"'{file_obj.name}' is not a supported file type. "
            f"Please upload one of: {allowed}."
        )

    size_bytes = file_obj.size
    if size_bytes > UPLOADS_MAX_BYTES:
        size_mb = size_bytes / (1024 * 1024)
        limit_mb = UPLOADS_MAX_BYTES / (1024 * 1024)
        raise ValidationError(
            f"File is too large ({size_mb:.1f} MB). "
            f"Maximum allowed size is {limit_mb:.0f} MB."
        )


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def save_upload(file_obj, store_id: int) -> Path:
    """Save a validated uploaded file to the store's upload directory
    with a unique filename.

    Filename format: {YYYYMMDD_HHMMSS}_{8-char-uuid}_{original-stem}.{ext}

    The timestamp provides natural sort order when browsing the folder;
    the UUID segment guarantees uniqueness even if two stores upload a
    file with the same original name at the same second; the original
    stem preserves human readability.

    This function does NOT validate the file - call validate_upload()
    before calling this. Separating validation from saving lets the UI
    show all validation errors before any disk I/O happens.

    Args:
        file_obj: A validated Streamlit UploadedFile.
        store_id: The currently logged-in store's ID.

    Returns:
        The absolute Path where the file was saved.
    """
    store_dir = get_store_upload_dir(store_id)

    original_stem = Path(file_obj.name).stem
    # Sanitize: replace spaces and characters that cause filesystem or
    # URL headaches with underscores so the path is always safe to open.
    safe_stem = "".join(
        c if (c.isalnum() or c in "-_") else "_"
        for c in original_stem
    )[:40]  # cap length to avoid overly long filenames on Windows paths

    ext = Path(file_obj.name).suffix.lstrip(".").lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid_short = uuid.uuid4().hex[:8]
    filename = f"{timestamp}_{uid_short}_{safe_stem}.{ext}"

    dest_path = store_dir / filename
    dest_path.write_bytes(file_obj.getvalue())

    return dest_path


# ---------------------------------------------------------------------------
# Preview generation
# ---------------------------------------------------------------------------

def get_image_preview(file_obj) -> Image.Image:
    """Return a PIL Image for a JPG/PNG upload, ready to pass to
    st.image().

    Args:
        file_obj: A Streamlit UploadedFile with an image extension.

    Returns:
        A PIL Image object.

    Raises:
        ValidationError: If the file bytes cannot be decoded as an image
            (e.g. a file with a .jpg extension that is actually corrupt
            or a different format entirely).
    """
    try:
        return Image.open(io.BytesIO(file_obj.getvalue()))
    except Exception as exc:
        raise ValidationError(
            f"Could not read image file '{file_obj.name}'. "
            "The file may be corrupt or in an unsupported format."
        ) from exc


def get_pdf_preview(file_obj) -> Image.Image | None:
    """Rasterize the first page of a PDF to a PIL Image for preview.

    Uses PyMuPDF (fitz) to render at PDF_PREVIEW_DPI. Returns None if
    rasterization fails for any reason (encrypted PDF, corrupt file,
    etc.) so callers can fall back to showing metadata instead of
    crashing.

    No temp file is written - the rasterized page is kept in memory
    as a PIL Image and discarded after the Streamlit render call.

    Args:
        file_obj: A Streamlit UploadedFile with a .pdf extension.

    Returns:
        A PIL Image of the first page, or None if preview is not
        possible.
    """
    try:
        import fitz  # PyMuPDF - imported here (not at module top) so
                     # the rest of file_utils remains usable even if
                     # pymupdf is not installed (e.g. during unit tests
                     # that only exercise image validation).

        pdf_bytes = file_obj.getvalue()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if len(doc) == 0:
            return None

        page = doc[0]
        mat = fitz.Matrix(PDF_PREVIEW_DPI / 72, PDF_PREVIEW_DPI / 72)
        pix = page.get_pixmap(matrix=mat)

        # Convert PyMuPDF Pixmap to PIL Image in memory - no temp file.
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
        return img
    except Exception:
        return None


def get_pdf_info(file_obj) -> dict:
    """Extract basic metadata from a PDF for fallback display when
    rasterization is not possible.

    Args:
        file_obj: A Streamlit UploadedFile with a .pdf extension.

    Returns:
        A dict with keys: page_count (int), file_size_mb (float),
        filename (str). Values are safe defaults if extraction fails.
    """
    filename = file_obj.name
    size_mb = len(file_obj.getvalue()) / (1024 * 1024)
    page_count = 0

    try:
        import fitz
        doc = fitz.open(stream=file_obj.getvalue(), filetype="pdf")
        page_count = len(doc)
        doc.close()
    except Exception:
        pass

    return {
        "filename": filename,
        "page_count": page_count,
        "file_size_mb": round(size_mb, 2),
    }
