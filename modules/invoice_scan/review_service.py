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
import uuid

import streamlit as st

from modules.invoice_scan.ocr_service import MEDICINE_FIELDS, INVOICE_HEADER_FIELDS
from modules.invoice_scan.validation import validate_medicines

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
    invoice_header: dict = None,
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
        invoice_header:  Optional agency name / bill number / bill date /
            grand total read from the invoice (INVOICE_HEADER_FIELDS
            keys). Editable in the Review screen; missing keys and None
            become empty strings.
    """
    
    rows = copy.deepcopy(medicines)
    for row in rows:
        row.setdefault("_row_id", uuid.uuid4().hex)

    # Validation Layer: runs exactly once here, immediately after Gemini
    # extraction and before the row ever reaches the editable Review
    # table. Deterministic and advisory only - it attaches a temporary
    # "_validation" flags dict to each row and never modifies any
    # extracted field, never calls Gemini, and never blocks anything
    # downstream (Review and Save behave exactly as before).
    rows = validate_medicines(rows)

    st.session_state[_SESSION_KEY] = {
        "file_hash": file_hash,
        "source_file": source_filename,
        "medicines": rows,
        "ocr_metadata": ocr_metadata or {},
        "invoice_header": {
            field: str((invoice_header or {}).get(field) or "")
            for field in INVOICE_HEADER_FIELDS
        },
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


def _clear_review_widget_keys() -> None:
    """Remove every per-row widget key left behind in session_state -
    both the editable text_input keys ("review_row_...") and the
    per-row delete button keys ("delete_row_...").

    Bug fix (Sprint 2.1): clear_session() previously swept only
    "review_row_" keys. "delete_row_{row_id}" keys (one per medicine,
    from each row's delete button) were never removed here, even
    though delete_medicine() already cleans up both prefixes correctly
    for a single deleted row. This is the single shared sweep used by
    every full-session teardown so both prefixes are always handled
    together, in one place.
    """
    stale_keys = [
        k for k in list(st.session_state.keys())
        if k.startswith("review_row_")
        or k.startswith("delete_row_")
        or k.startswith("review_header_")
    ]
    for k in stale_keys:
        del st.session_state[k]


def clear_session() -> None:
    """Remove the review session and all related widget keys.

    Called when the user explicitly clicks 'Clear / New Invoice'. Also
    removes the file_uploader widget key so the uploader resets to an
    empty state immediately after st.rerun() - safe here specifically
    because this path always runs on a rerun where the uploader has not
    yet been re-instantiated with a new file.

    Not used for the automatic new-upload reset (a different file was
    just uploaded, same script run) - see
    reset_session_for_new_upload() for that case, which must NOT touch
    "invoice_file_uploader" while it is already instantiated this run.
    """
    st.session_state.pop(_SESSION_KEY, None)
    # Remove the file uploader widget key so it resets to empty.
    st.session_state.pop("invoice_file_uploader", None)
    _clear_review_widget_keys()


def reset_session_for_new_upload() -> None:
    """Completely destroy any previous review session before a new
    invoice's extraction begins.

    Bug fix (Sprint 2.1): a newly uploaded invoice (different SHA-256
    hash from whatever session, if any, is currently active) must
    always start from a completely clean state - the previous
    session's medicine rows, their validation flags/warnings (both
    live inside the same session dict removed here), OCR metadata,
    cached save result, and every per-row widget key are all torn down
    before the new extraction's initialise_review_session() call
    creates a fresh session. This never requires the user to press
    'Clear Review' - it runs automatically as part of the upload flow.

    Deliberately does NOT touch "invoice_file_uploader": unlike
    clear_session() (used for the explicit user-initiated Clear
    button, on a rerun where the uploader is not yet re-instantiated),
    this function runs in the same script run where the uploader
    widget has already been instantiated with the newly uploaded file
    - clearing its key here would fight the widget's own state
    mid-run instead of simply replacing the review data underneath it.

    The existing SHA-256 cache logic is unaffected: this is only ever
    called when is_review_session_active(new_file_hash) is False (see
    upload_ui.py) - an identical re-upload of the same file still
    correctly reuses the cached session with no Gemini re-call.
    """
    st.session_state.pop(_SESSION_KEY, None)
    _clear_review_widget_keys()

def get_invoice_header() -> dict:
    """Return the current (editable) invoice header: agency_name,
    invoice_number, invoice_date, grand_total - all strings. Every
    field is "" if there is no session."""
    session = st.session_state.get(_SESSION_KEY)
    stored = session.get("invoice_header", {}) if session else {}
    return {field: str(stored.get(field) or "") for field in INVOICE_HEADER_FIELDS}


def update_invoice_header(field: str, value: str) -> None:
    """Store one edited header field. Unknown fields and a missing
    session are ignored."""
    session = st.session_state.get(_SESSION_KEY)
    if session is None or field not in INVOICE_HEADER_FIELDS:
        return
    session.setdefault("invoice_header", {})[field] = value


def parse_amount(text) -> float:
    """Parse a typed rupee amount ("1515", "1,515.50", "₹ 1515.5")
    into a float, or return None if it is empty, not a number, or not
    greater than zero."""
    cleaned = str(text or "").strip()
    for junk in ("₹", "Rs.", "Rs", "INR", ",", " "):
        cleaned = cleaned.replace(junk, "")
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return number if number > 0 else None


def validate_invoice_header(header: dict) -> dict:
    """Return {field: message} for header fields that need attention.

    Agency name and grand total are required (a bill cannot be added to
    an agency's ledger without them); a grand total that is present
    must be a positive number. Bill number and date are optional.
    Purely advisory for now - nothing is blocked by this yet.
    """
    problems = {}
    if not str(header.get("agency_name") or "").strip():
        problems["agency_name"] = "Agency name is required."

    total_text = str(header.get("grand_total") or "").strip()
    if not total_text:
        problems["grand_total"] = "Grand total is required."
    elif parse_amount(total_text) is None:
        problems["grand_total"] = "Enter a valid amount (numbers only)."
    return problems

def get_ocr_metadata() -> dict:
    """Return cached OCR metrics (count, time, model). Empty dict if none."""
    session = st.session_state.get(_SESSION_KEY)
    return session.get("ocr_metadata", {}) if session else {}


def get_medicines() -> list:
    """Return the current editable medicine list. Empty list if none."""
    session = st.session_state.get(_SESSION_KEY)
    return session.get("medicines", []) if session else []


def get_medicines_with_live_warnings() -> list:
    """Return the current medicine list with advisory validation flags
    recomputed fresh from each row's CURRENT values, instead of the
    stale "_validation" snapshot attached once in
    initialise_review_session() at OCR time.

    Warnings sprint: this does not change any warning RULE - it calls
    the exact same validation.validate_medicines() used at session
    init, on the exact same live list get_medicines() already returns
    (mutated in place, same object), just on every call instead of
    only once. Callers (review_ui.py) use this instead of
    get_medicines() wherever advisory flags are read, so a warning
    appears or disappears immediately as the reviewer edits a field,
    on the very next rerun - never a click or extra action needed.
    """
    return validate_medicines(get_medicines())


def update_medicine(index: int, field: str, value: str) -> None:
    """Update one field in one medicine row (local state only, no DB)."""
    medicines = get_medicines()
    if 0 <= index < len(medicines):
        medicines[index][field] = value
        st.session_state[_SESSION_KEY]["medicines"] = medicines


def delete_medicine(index: int) -> None:
    """Remove the medicine at index (local state only, no DB).

    Also removes this row's own widget keys (text inputs + delete
    button), identified by its stable _row_id rather than its position,
    so no other row's widget can ever inherit stale session_state left
    behind by the row that was just removed.
    """
    medicines = get_medicines()
    if 0 <= index < len(medicines):
        row_id = medicines[index].get("_row_id")
        medicines.pop(index)
        st.session_state[_SESSION_KEY]["medicines"] = medicines

        if row_id:
            stale_keys = [
                k for k in list(st.session_state.keys())
                if k.startswith(f"review_row_{row_id}_") or k == f"delete_row_{row_id}"
            ]
            for k in stale_keys:
                del st.session_state[k]


def add_empty_medicine() -> None:
    """Append a blank medicine row (local state only, no DB)."""
    empty_row = {field: "" for field in MEDICINE_FIELDS}
    empty_row["_row_id"] = uuid.uuid4().hex
    medicines = get_medicines()
    medicines.append(empty_row)
    st.session_state[_SESSION_KEY]["medicines"] = medicines


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_invoice_medicines(store_id: int) -> dict:
    """Write all reviewed medicines to the products database, using the
    stock-lot identity/merge rules (see
    modules.products.service's "Stock Lot identity & merge rules"
    section - the single centralized place those rules live).

    Called ONLY when the store owner clicks '💾 Save Medicines'. Until
    that moment every edit, delete, and add is purely local.

    Iterates the current medicine list and calls
    products_service.save_or_merge_invoice_lot for each row. A row
    whose incoming batch number is blank and possibly matches an
    existing lot with a real batch number is NOT saved yet - it is
    collected as a "pending match" for the store owner to confirm
    (see get_pending_matches/resolve_pending_match below) rather than
    being silently merged or silently duplicated. Rows that fail
    validation are collected as skipped entries — partial success is
    better than all-or-nothing.

    Args:
        store_id: From core.session.get_current_store_id().

    Returns:
        {"saved": int, "skipped": [{"row", "name", "error"}, ...],
         "pending": int}
    """
    from modules.products.service import save_or_merge_invoice_lot
    from core.exceptions import ValidationError

    medicines = get_medicines()
    saved = 0
    skipped = []
    pending_matches = []

    for idx, row in enumerate(medicines):
        lot_data = {
            "name":         row.get("name", ""),
            "batch_number": row.get("batch_number", ""),
            "expiry_date":  row.get("expiry_date", ""),
            "quantity":     row.get("quantity", ""),
            "mrp":          row.get("mrp", ""),
            "rate":         row.get("rate", ""),
            "gst_percent":  row.get("gst_percent", ""),
            "purchase_date": "",
        }
        try:
            outcome = save_or_merge_invoice_lot(store_id, lot_data)
            if outcome["status"] == "needs_confirmation":
                pending_matches.append({
                    "row": idx + 1,
                    "name": row.get("name", "(unnamed)"),
                    "lot_data": lot_data,
                    "match": outcome["match"],
                })
            else:
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

    result = {"saved": saved, "skipped": skipped, "pending": len(pending_matches)}
    if _SESSION_KEY in st.session_state:
        st.session_state[_SESSION_KEY]["save_result"] = result
        st.session_state[_SESSION_KEY]["pending_matches"] = pending_matches
    return result


def get_save_result() -> dict | None:
    """Return the result of the last Save operation, or None."""
    session = st.session_state.get(_SESSION_KEY)
    return session.get("save_result") if session else None


def get_pending_matches() -> list:
    """Return the "possible match found" rows left over from the last
    Save that still need the store owner's Yes/Create New decision
    (see save_invoice_medicines). Empty list if there are none, or no
    session is active.
    """
    session = st.session_state.get(_SESSION_KEY)
    return session.get("pending_matches", []) if session else []


def resolve_pending_match(pending_index: int, decision: str) -> dict:
    """Resolve one pending possible-match row after the store owner
    clicks "Yes" (merge into the existing lot) or "Create New" (save
    as its own new lot, batch number left blank).

    Args:
        pending_index: Index into get_pending_matches()'s list.
        decision: "merge" or "create_new".

    Returns:
        The same outcome dict save_or_merge_invoice_lot returns
        ({"status": "merged"/"created", "product_id": int}).

    Raises:
        ValidationError: If the row's data fails validation (should
            not normally happen here, since it already passed once).
    """
    from modules.products.service import save_or_merge_invoice_lot
    from core.session import get_current_store_id

    pending = get_pending_matches()
    entry = pending[pending_index]
    store_id = get_current_store_id()

    if decision == "merge":
        outcome = save_or_merge_invoice_lot(
            store_id, entry["lot_data"], merge_into_product_id=entry["match"]["product_id"]
        )
    else:
        outcome = save_or_merge_invoice_lot(store_id, entry["lot_data"], force_new=True)

    remaining = [p for i, p in enumerate(pending) if i != pending_index]
    if _SESSION_KEY in st.session_state:
        st.session_state[_SESSION_KEY]["pending_matches"] = remaining
        save_result = st.session_state[_SESSION_KEY].get("save_result")
        if save_result:
            save_result["saved"] = save_result.get("saved", 0) + 1
            save_result["pending"] = len(remaining)

    return outcome


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_medicine(row: dict) -> list:
    """Validate one medicine row. Returns list of error strings (empty = valid).

    Required fields (blank is ALWAYS a blocking error): Medicine Name,
    Batch Number, Expiry, Quantity, MRP, Rate, GST %.

    Stabilization sprint fix: Quantity/MRP/Rate/GST % were previously
    only checked with "if val and not _is_numeric(val)" - meaning a
    BLANK value for any of them silently passed validation, even though
    they are required fields. That let a row with a filled-in name but
    blank MRP/Rate/Qty/GST slip through with no blocking error at all
    (no red highlight, Save not blocked) - now fixed: each of these four
    fields is validated as "must be present, and if present, must be
    numeric" - two separate, clearly worded errors depending on which
    condition fails.

    RED-validation sprint: Batch Number and Expiry were previously
    optional (blank was valid; only an invalid Expiry *format* blocked
    Save). Both are now required, same as the other five fields - blank
    now blocks Save for either. Expiry's existing format check is
    unchanged and still applies whenever a value is present.

    Warnings sprint: message wording only was rewritten to be short and
    owner-friendly (e.g. "Medicine name is required." instead of
    "Medicine Name cannot be empty."). No field's required/optional
    status or trigger condition changed - same fields, same blank/
    invalid checks, same order. modules/invoice_scan/review_ui.py's
    _BLOCKING_FIELD_INFO was updated in lockstep so field highlighting
    still matches each message.
    """
    errors = []

    name = row.get("name", "").strip()
    if not name:
        errors.append("Medicine name is required.")

    batch = row.get("batch_number", "").strip()
    if not batch:
        errors.append("Batch number is required.")

    expiry = row.get("expiry_date", "").strip()
    if not expiry:
        errors.append("Expiry is required.")
    elif not _is_valid_expiry(expiry):
        errors.append("Enter a valid expiry date.")

    for field_key, required_label, invalid_label in [
        ("quantity", "Quantity is required.", "Enter a valid quantity."),
        ("mrp", "MRP is required.", "Enter a valid MRP."),
        ("rate", "Rate is required.", "Enter a valid rate."),
        ("gst_percent", "GST is required.", "Enter a valid GST value."),
    ]:
        val = row.get(field_key, "").strip()
        if not val:
            errors.append(required_label)
        elif not _is_numeric(val):
            errors.append(invalid_label)

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
