"""
Review & Edit service for invoice OCR results.

Owns three concerns:
  1. Session state management — initialising, reading, and mutating the
     editable medicine list that lives in st.session_state.
  2. Row-level validation — checking medicine dicts before save.
  3. Save — writing validated medicines to the products table in one
     pass when the store owner clicks "Save Inventory".

Identity model: sessions are keyed by SHA-256 hash of the uploaded
file's bytes, NOT by filename. Two files with the same name but
different content produce different hashes and therefore different
sessions. Uploading the identical file twice reuses the existing
session correctly (no OCR rerun).
"""

import copy
import hashlib
import re

import streamlit as st

from modules.invoice_scan.ocr_service import MEDICINE_FIELDS

_SESSION_KEY = "invoice_review"


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------

def compute_file_hash(file_bytes: bytes) -> str:
    """Return SHA-256 hex digest of uploaded file bytes.

    Used as the session identity key instead of filename so that two
    files with the same name but different content never share a session.

    Args:
        file_bytes: Raw bytes from uploaded_file.getvalue().

    Returns:
        64-character lowercase hex string.
    """
    return hashlib.sha256(file_bytes).hexdigest()


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

def initialise_review_session(
    file_hash: str,
    source_filename: str,
    medicines: list,
    ocr_metadata: dict = None,
) -> None:
    """Populate the review session from an OCR result.

    Called exactly once per unique file (identified by SHA-256 hash).
    On every subsequent Streamlit rerun, is_review_session_active()
    returns True and callers skip OCR entirely.

    Args:
        file_hash:       SHA-256 hex digest of the uploaded file bytes.
        source_filename: Original filename, stored for display only.
        medicines:       Medicine dicts from ocr_service. Deep-copied.
        ocr_metadata:    Optional OCR metrics (count, time, model).
    """
    st.session_state[_SESSION_KEY] = {
        "file_hash": file_hash,
        "source_file": source_filename,
        "medicines": copy.deepcopy(medicines),
        "ocr_metadata": ocr_metadata or {},
        "save_result": None,
    }


def is_review_session_active(file_hash: str) -> bool:
    """Return True if a review session exists for this exact file hash.

    Args:
        file_hash: SHA-256 hex digest of the currently uploaded file.
    """
    session = st.session_state.get(_SESSION_KEY)
    if session is None:
        return False
    return session.get("file_hash") == file_hash


def has_any_session() -> bool:
    """Return True if any review session exists (regardless of file).

    Used by the navigation-persistence path: when uploaded_file is None
    (user navigated away and returned), the UI renders the cached session.
    """
    return _SESSION_KEY in st.session_state


def get_session_filename() -> str:
    """Return the source filename stored in the active session, or ''."""
    session = st.session_state.get(_SESSION_KEY)
    return session.get("source_file", "") if session else ""


def clear_session() -> None:
    """Remove the review session and all related widget keys.

    Called when a different invoice is uploaded (new hash) or when the
    user explicitly clicks 'Clear / New Invoice'.

    Also removes the file_uploader widget key so the uploader resets to
    an empty state immediately after st.rerun().
    """
    st.session_state.pop(_SESSION_KEY, None)
    # Remove the file uploader widget key so it resets to empty.
    st.session_state.pop("invoice_file_uploader", None)
    # Remove all review table row widget keys.
    stale_keys = [
        k for k in list(st.session_state.keys())
        if k.startswith("review_row_")
    ]
    for k in stale_keys:
        del st.session_state[k]


def get_ocr_metadata() -> dict:
    """Return cached OCR metrics (count, time, model). Empty dict if none."""
    session = st.session_state.get(_SESSION_KEY)
    return session.get("ocr_metadata", {}) if session else {}


def get_medicines() -> list:
    """Return the current editable medicine list. Empty list if none."""
    session = st.session_state.get(_SESSION_KEY)
    return session.get("medicines", []) if session else []


def update_medicine(index: int, field: str, value: str) -> None:
    """Update one field in one medicine row (local state only, no DB)."""
    medicines = get_medicines()
    if 0 <= index < len(medicines):
        medicines[index][field] = value
        st.session_state[_SESSION_KEY]["medicines"] = medicines


def delete_medicine(index: int) -> None:
    """Remove the medicine at index (local state only, no DB)."""
    medicines = get_medicines()
    if 0 <= index < len(medicines):
        medicines.pop(index)
        st.session_state[_SESSION_KEY]["medicines"] = medicines


def add_empty_medicine() -> None:
    """Append a blank medicine row (local state only, no DB)."""
    empty_row = {field: "" for field in MEDICINE_FIELDS}
    medicines = get_medicines()
    medicines.append(empty_row)
    st.session_state[_SESSION_KEY]["medicines"] = medicines


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_invoice_medicines(store_id: int) -> dict:
    """Write all reviewed medicines to the products database.

    Called ONLY when the store owner clicks '💾 Save Inventory'. Until
    that moment every edit, delete, and add is purely local.

    Iterates the current medicine list and calls products_service.add_product
    for each row. Rows that fail validation or already exist are collected
    as skipped entries — partial success is better than all-or-nothing.

    Args:
        store_id: From core.session.get_current_store_id().

    Returns:
        {"saved": int, "skipped": [{"row", "name", "error"}, ...]}
    """
    from modules.products.service import add_product
    from core.exceptions import ValidationError

    medicines = get_medicines()
    saved = 0
    skipped = []

    for idx, row in enumerate(medicines):
        form_data = {
            "name":         row.get("name", ""),
            "batch_number": row.get("batch_number", ""),
            "expiry_date":  row.get("expiry_date", ""),
            "quantity":     row.get("quantity", ""),
            "mrp":          row.get("mrp", ""),
            "rate":         row.get("rate", ""),
            "gst_percent":  row.get("gst_percent", ""),
            "purchase_date": "",
            "_minimum_stock_threshold_enabled": False,
            "minimum_stock_threshold": None,
        }
        try:
            add_product(store_id, form_data)
            saved += 1
        except ValidationError as exc:
            skipped.append({
                "row":   idx + 1,
                "name":  row.get("name", "(unnamed)"),
                "error": str(exc),
            })
        except Exception as exc:
            skipped.append({
                "row":   idx + 1,
                "name":  row.get("name", "(unnamed)"),
                "error": f"Unexpected error: {exc}",
            })

    result = {"saved": saved, "skipped": skipped}
    if _SESSION_KEY in st.session_state:
        st.session_state[_SESSION_KEY]["save_result"] = result
    return result


def get_save_result() -> dict | None:
    """Return the result of the last Save operation, or None."""
    session = st.session_state.get(_SESSION_KEY)
    return session.get("save_result") if session else None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_medicine(row: dict) -> list:
    """Validate one medicine row. Returns list of error strings (empty = valid)."""
    errors = []

    name = row.get("name", "").strip()
    if not name:
        errors.append("Medicine Name cannot be empty.")

    expiry = row.get("expiry_date", "").strip()
    if expiry and not _is_valid_expiry(expiry):
        errors.append(
            "Expiry must be in Month/Year format (MM/YY, MM/YYYY or Month-YYYY)."
        )

    for field_key, label in [
        ("quantity", "Quantity"),
        ("mrp", "MRP"),
        ("rate", "Rate"),
        ("gst_percent", "GST %"),
    ]:
        val = row.get(field_key, "").strip()
        if val and not _is_numeric(val):
            errors.append(f"{label} must be a number (got '{val}').")

    return errors


def validate_all_medicines() -> dict:
    """Validate all rows. Returns {row_index: [errors]} for failing rows."""
    errors_by_row = {}
    for idx, row in enumerate(get_medicines()):
        row_errors = validate_medicine(row)
        if row_errors:
            errors_by_row[idx] = row_errors
    return errors_by_row


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _is_numeric(value: str) -> bool:
    try:
        return float(value) >= 0
    except (ValueError, TypeError):
        return False


def _is_valid_expiry(value: str) -> bool:
    """Thin wrapper — delegates to the canonical validator in utils.validators
    so review_service and products/service use the exact same logic."""
    from utils.validators import is_valid_expiry
    return is_valid_expiry(value)
