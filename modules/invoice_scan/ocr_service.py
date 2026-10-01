"""
Invoice OCR extraction service using Gemini Vision.

This is the only file added by Module 3 (OCR). Narrow scope:
  - Read the API key from environment (never hardcoded)..
  - Convert the uploaded file to a PIL Image (reuses file_utils).
  - Send the image to Gemini Vision with a strict JSON-only prompt.
  - Parse and validate the response.
  - Return a structured result dict.

No Streamlit imports. No database access. No writes of any kind.
"""

import io
import json
import os
import time
import base64
from pathlib import Path
from PIL import Image, ImageOps, ImageEnhance
import google.genai as genai
from google.genai import types as genai_types

from config.settings import DEBUG_PREPROCESSING, GEMINI_MODEL, GEMINI_TIMEOUT_SECONDS
from core.exceptions import GeminiAPIError, OCRError
from utils.file_utils import get_image_preview, get_pdf_preview

# .env is loaded once, at import time, by config/settings.py itself (the
# earliest-imported module in the app) - not here. See that file's own
# comment for why loading it there, rather than here, is what makes
# environment-derived settings (like DEBUG_PREPROCESSING) actually work
# regardless of import order.

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def _emergent_preprocess(raw: bytes) -> str:
    """Prepare a photo for a VISION model (not classic OCR).
    - fix EXIF orientation
    - keep enough resolution so tiny batch/expiry digits survive
    - adaptive lighting fix (dark AND washed-out photos)
    - mild sharpen for faint dot-matrix / carbon-copy print
    We do NOT binarize/threshold - that hurts LLM vision.
    """
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)

    if img.mode != "RGB":
        img = img.convert("RGB")

    # was 2200 - too low for dense 15-20 item bills; 3000 keeps digits legible
    max_side = 3000
    if max(img.size) > max_side:
        ratio = max_side / max(img.size)
        img = img.resize(
            (int(img.size[0] * ratio), int(img.size[1] * ratio)),
            Image.LANCZOS,
        )

    # adaptive, replaces the old fixed Contrast(1.15)
    img = ImageOps.autocontrast(img, cutoff=1)
    # modest sharpen - recovers faint print without artifacts
    img = ImageEnhance.Sharpness(img).enhance(1.5)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)  # 95 keeps small digits crisp
    return base64.b64encode(buf.getvalue()).decode("utf-8")

# def _emergent_preprocess(raw: bytes) -> str:
#     img = Image.open(io.BytesIO(raw))
#     img = ImageOps.exif_transpose(img)

#     if img.mode != "RGB":
#         img = img.convert("RGB")

#     max_side = 2200

#     if max(img.size) > max_side:
#         ratio = max_side / max(img.size)
#         img = img.resize(
#             (
#                 int(img.size[0] * ratio),
#                 int(img.size[1] * ratio),
#             ),
#             Image.LANCZOS,
#         )

#     img = ImageEnhance.Contrast(img).enhance(1.15)

#     buf = io.BytesIO()
#     img.save(buf, format="JPEG", quality=92)

#     return base64.b64encode(buf.getvalue()).decode("utf-8")

MEDICINE_FIELDS = [
    "name",
    "batch_number",
    "expiry_date",
    "qty",
    "free",
    "tqt",
    "mrp",
    "rate",
    "gst_percent",
]

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_PROMPT_FIELDS = ["name", "batch_number", "expiry_date", "qty", "free", "mrp", "rate", "gst_percent"]

INVOICE_HEADER_FIELDS = ["agency_name", "invoice_date", "grand_total"]

_EXTRACTION_PROMPT = f"""
You are an expert at reading Indian medical-store GST purchase invoices from photos.

The image is a photo of ONE invoice. It may be rotated, skewed, folded, low-contrast, or have a busy background. First mentally correct the orientation, locate the main line-item TABLE, read its HEADER ROW, identify the column boundaries, then read each medicine row.

Extract EVERY medicine line item (one object per row). For each row return EXACTLY these fields:

- "name": value from the PRODUCT NAME / PRODUCT / ITEM NAME column. Not HSN, batch, packaging, manufacturer, qty, mrp or rate. Preserve it as printed.
- "batch_number": value from the BATCH NO / BATCH column. Not HSN, invoice no, product code, or expiry. Preserve letters and digits exactly.
- "expiry_date": value from the EXP / EXPIRY column, kept in the invoice's own month/year form (e.g. "2/29", "08/27", "05/27", "11/28"). Do NOT reformat.
- "qty": value from the QTY / QUANTITY column (actual purchased/paid quantity). NEVER put the FREE, TQT, or a packaging number here. If both QTY and FREE exist, put only the QTY value here.
- "free": value from the FREE column (bonus/free quantity). If there is no free column or it is empty/zero, set it to "0". Do NOT mix this up with the paid QTY.
- "mrp": value from the MRP / M.R.P column. Not RATE, not amount, not taxable value.
- "rate": value from the RATE column. Do NOT substitute MRP. MRP and Rate are separate.
- "gst_percent": the percentage from the GST / GST % column (e.g. "5", "12", "18"). Do NOT use CGST/SGST amounts, GST total amount, or discount %.

CRITICAL RULES:
1. Keep row-to-column alignment perfect. A medicine must never receive another row's batch/expiry/mrp/qty.
2. Distinguish look-alike characters carefully: O vs 0, I vs 1, S vs 5, B vs 8, z vs 2 decimal points, and the slash in expiry.
3. Do NOT invent, calculate, or infer any missing value. If a field is not clearly readable, set it to "" (empty string). Never copy a value from another row to fill a gap.
4. Only extract the medicine line items - ignore header/address/totals/tax-summary sections.

Also read the invoice's header/footer (once for the whole invoice, not per row) and return these 4 extra fields:

- "agency_name": the name of the SELLER - the distributor / agency / wholesaler that ISSUED this bill (normally printed large at the top, often with its address, GSTIN and drug licence numbers). NOT the buyer / "Bill To" / "Customer" / medical store the goods are sold to, and NOT a manufacturer or a product name. Preserve the name as printed.
- "invoice_date": the invoice / bill date exactly as printed (e.g. "25-07-2026", "25/07/26", "25-Jul-2026"). NOT an expiry date, due date or print time.
- "grand_total": the FINAL total amount payable for the whole invoice (labels like "Grand Total", "Net Amount", "Net Payable", "Invoice Value", "Total Amount"). Digits and decimal point only - no currency symbol, no commas. NOT a sub-total, NOT the GST / tax total, NOT the discount total, NOT a single row's amount, and NOT a round-off value. Use the PRINTED value only, ignoring handwritten pen marks/ticks/circles. If not clearly readable, set it to "".

Return ONLY valid JSON, no markdown, no commentary. Return a single JSON OBJECT (not an array) with EXACTLY these keys:
{json.dumps(INVOICE_HEADER_FIELDS + ["medicines"])}

"medicines" is a JSON array, one element per medicine row, with EXACTLY these keys per object:
{json.dumps(_PROMPT_FIELDS)}

If no medicines are found, or the image is unreadable / not an invoice, set "medicines" to [] and every header field to "".
"""

# Forces Gemini to return clean, complete JSON matching exactly this shape:
# the 4 header fields plus "medicines" (an array of objects with exactly
# these 8 keys). This (not the prompt text) is what kills bad-JSON /
# missing-field failures.
_MEDICINE_ITEM_SCHEMA = genai_types.Schema(
    type=genai_types.Type.OBJECT,
    properties={f: genai_types.Schema(type=genai_types.Type.STRING) for f in _PROMPT_FIELDS},
    required=list(_PROMPT_FIELDS),
    property_ordering=list(_PROMPT_FIELDS),
)

_RESPONSE_SCHEMA = genai_types.Schema(
    type=genai_types.Type.OBJECT,
    properties={
        **{f: genai_types.Schema(type=genai_types.Type.STRING) for f in INVOICE_HEADER_FIELDS},
        "medicines": genai_types.Schema(type=genai_types.Type.ARRAY, items=_MEDICINE_ITEM_SCHEMA),
    },
    required=INVOICE_HEADER_FIELDS + ["medicines"],
    property_ordering=INVOICE_HEADER_FIELDS + ["medicines"],
)


def _clean_header_text(value) -> str:
    """Collapse whitespace and trim; anything that is not a string-like
    value becomes an empty string."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _clean_header_amount(value) -> str:
    """Turn what Gemini returned for the grand total into a plain
    "1515.00"-style string, or "" if it is not a usable positive
    number (the store owner then types it in by hand)."""
    text = str(value or "").strip()
    for junk in ("\u20b9", "Rs.", "Rs", "INR", ",", " "):
        text = text.replace(junk, "")
    try:
        number = float(text)
    except ValueError:
        return ""
    if number <= 0:
        return ""
    return f"{number:.2f}"


# ---------------------------------------------------------------------------
# Key loading
# ---------------------------------------------------------------------------

# Up to 3 Gemini API keys, ideally from 3 SEPARATE Google accounts/
# projects so each has its own independent free-tier quota. Only the
# ones actually set are used - a deployment with just GEMINI_API_KEY_1
# (or the original single GEMINI_API_KEY) keeps working exactly as
# before, with no rotation.
_GEMINI_API_KEY_ENV_VARS = ("GEMINI_API_KEY_1", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3")

# Which configured key is currently "active". Shared by the whole app
# (every store), not per-store, since it tracks which Google
# account/key is currently working - not anything specific to one
# store's data. Lives only in this server process's memory: it starts
# back at the first configured key whenever the app process restarts
# (e.g. a Streamlit Cloud redeploy or the app waking from sleep).
_active_key_index = 0


def _get_configured_api_keys() -> list:
    """Return every configured Gemini API key, in order.

    Checks GEMINI_API_KEY_1/_2/_3 first; if none of those are set,
    falls back to the single GEMINI_API_KEY variable this app used
    before key rotation existed, so older deployments are unaffected.

    Raises:
        GeminiAPIError: If no key at all is configured.
    """
    keys = []
    for var_name in _GEMINI_API_KEY_ENV_VARS:
        value = os.environ.get(var_name, "").strip()
        if value:
            keys.append(value)

    if not keys:
        single_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if single_key:
            keys.append(single_key)

    if not keys:
        raise GeminiAPIError(
            "Gemini API key not found. Please add GEMINI_API_KEY_1 "
            "(and optionally GEMINI_API_KEY_2 / _3) to this app's "
            "environment or Secrets, and restart the app."
        )
    return keys

def _get_api_key() -> str:
    """Return the first configured Gemini API key.

    Kept so older callers/tests that expect a single key keep working;
    the extraction itself uses _get_configured_api_keys() and rotates.

    Raises:
        GeminiAPIError: If no key is configured.
    """
    return _get_configured_api_keys()[0]

# ---------------------------------------------------------------------------
# Image preparation
# ---------------------------------------------------------------------------

def _file_to_pil_image(file_obj) -> Image.Image:
    """Convert a Streamlit UploadedFile (image or PDF) to a PIL Image.

    Reuses get_image_preview and get_pdf_preview from utils/file_utils.

    Raises:
        OCRError: If the file cannot be converted to an image.
    """
    ext = Path(file_obj.name).suffix.lstrip(".").lower()

    if ext == "pdf":
        img = get_pdf_preview(file_obj)
        if img is None:
            raise OCRError(
                "Could not read this PDF for extraction. "
                "It may be encrypted, password-protected, or corrupt. "
                "Please try uploading a different file."
            )
        return img

    try:
        return get_image_preview(file_obj)
    except Exception as exc:
        raise OCRError(
            f"Could not read '{file_obj.name}' as an image. "
            "The file may be corrupt or in an unsupported format."
        ) from exc

# ---------------------------------------------------------------------------
# Response validation
# ---------------------------------------------------------------------------

def _parse_and_validate_response(raw_text: str) -> list:
    """Parse Gemini's text response as JSON and validate structure.

    Strips accidental markdown fences, parses JSON, drops malformed rows.

    Raises:
        OCRError: If the response cannot be parsed as JSON.
    """
    text = raw_text.strip()

    # Strip accidental markdown fences despite the prompt saying not to.
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OCRError(
            "Gemini returned a response that could not be parsed as JSON. "
            "This can happen with very low-quality scans. "
            "Please try again or upload a clearer image."
        ) from exc

    if not isinstance(parsed, list):
        raise OCRError(
            "Gemini returned an unexpected response format (expected a list). "
            "Please try again."
        )

    return _validate_medicine_rows(parsed)


def _validate_medicine_rows(parsed: list) -> list:
    """Normalise each row to exactly MEDICINE_FIELDS and drop rows that
    aren't dicts or have no name. Shared by _parse_and_validate_response()
    (kept for its own existing tests) and _parse_combined_response()
    below - identical row-by-row logic, used from both places.
    """
    valid_rows = []
    for row in parsed:
        if not isinstance(row, dict):
            continue
        normalised = {field: str(row.get(field, "")).strip() for field in MEDICINE_FIELDS}
        if not normalised["name"]:
            continue
        valid_rows.append(normalised)
    return valid_rows


def _parse_combined_response(raw_text: str) -> tuple:
    """Parse the ONE combined Gemini response - a JSON object holding
    the 4 invoice-header fields plus "medicines" (the array of medicine
    rows) - into (medicines, invoice_header).

    Reuses _validate_medicine_rows() for the medicines array, so a row
    is normalised/dropped by the exact same rule as the older
    array-only path.

    Raises:
        OCRError: If the response cannot be parsed as JSON, or the top
            level is not a JSON object.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OCRError(
            "Gemini returned a response that could not be parsed as JSON. "
            "This can happen with very low-quality scans. "
            "Please try again or upload a clearer image."
        ) from exc

    if not isinstance(parsed, dict):
        raise OCRError(
            "Gemini returned an unexpected response format (expected an object). "
            "Please try again."
        )

    medicines_raw = parsed.get("medicines", [])
    medicines = _validate_medicine_rows(medicines_raw if isinstance(medicines_raw, list) else [])

    invoice_header = {
        "agency_name": _clean_header_text(parsed.get("agency_name")),
        "invoice_number": _clean_header_text(parsed.get("invoice_number")),
        "invoice_date": _clean_header_text(parsed.get("invoice_date")),
        "grand_total": _clean_header_amount(parsed.get("grand_total")),
    }
    return medicines, invoice_header

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _apply_quantity_formula(medicines: list) -> list:
    """Compute the internal "quantity" value from each row's qty/free/tqt
    fields and overwrite it onto the row, in place.

    Runs immediately after extraction and before the Review Session is
    initialised (called from extract_medicines_from_file(), before its
    result is returned to the caller) - so review_service.py's session
    lifecycle is never touched by this feature.

    Formula:
        if tqt is present:    quantity = tqt
        elif free is present: quantity = qty + free
        else:                 quantity = qty

    Only "quantity" is written - qty/free/tqt are left as-is on the
    row. Everything downstream of extract_medicines_from_file() (Review
    Session, Review UI, Validation, Save, Database) continues to read
    "quantity" exactly as before this feature.
    """
    for row in medicines:
        tqt = str(row.get("tqt", "")).strip()
        if tqt:
            row["quantity"] = tqt
            continue

        free = str(row.get("free", "")).strip()
        qty = str(row.get("qty", "")).strip()

        if free:
            try:
                total = float(qty or 0) + float(free)
                row["quantity"] = str(int(total)) if total == int(total) else str(total)
            except ValueError:
                # Non-numeric qty/free - fall back to qty as-is so the
                # unchanged downstream validation surfaces the problem
                # the same way it always has for a bad quantity value.
                row["quantity"] = qty
            continue

        row["quantity"] = qty

    return medicines


def _build_genai_client(api_key: str):
    """Create and return a google.genai Client.

    Extracted as its own function so tests can patch it cleanly at the
    module level rather than patching the entire genai module.
    """
    return genai.Client(api_key=api_key)


def extract_medicines_from_file(file_obj) -> dict:
    """Extract medicine line items from an uploaded invoice file.

    Flow:
        1. Load API key from environment.
        2. Convert file to PIL Image (reusing file_utils).
        3. Preprocess the image once using _emergent_preprocess().
           If preprocessing fails, fall back to the original image.
        4. Send the (preprocessed or original) image to Gemini Vision
           with the JSON-only prompt.
        5. Parse and validate the response.
        6. Return a result dict (no DB writes).

    Args:
        file_obj: A Streamlit UploadedFile (JPG/JPEG/PNG/PDF).

    Returns:
        A dict with:
            medicines (list[dict]): Extracted rows (MEDICINE_FIELDS keys).
            medicine_count (int): len(medicines).
            extraction_time_seconds (float): Gemini round-trip time.
            model (str): The Gemini model name used.

    Raises:
        GeminiAPIError: API key missing/invalid, timeout, rate limit,
            network error. Always has a human-readable message for the UI.
        OCRError: File unreadable or Gemini response unparseable.
    """
    keys = _get_configured_api_keys()
    pil_image = _file_to_pil_image(file_obj)

    # OCR Architecture v1.0: run preprocessing exactly once, before
    # Gemini ever sees the image. preprocess_image() is itself
    # designed to never raise (QUALITY_RULES.md Section 8), but this
    # try/except is kept as an explicit second safeguard here too -
    # preprocessing must never be able to block extraction, under any
    # circumstance. On any failure, fall back to the original uploaded
    # image, completely unprocessed - exactly what Gemini received before
    # preprocessing existed.
    try:
        raw_bytes = file_obj.getvalue()
        preprocessed_base64 = _emergent_preprocess(raw_bytes)
        image_bytes = base64.b64decode(preprocessed_base64)
        image_mime_type = "image/jpeg"
        preprocess_result = None
    except Exception:
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        image_bytes = buf.getvalue()
        image_mime_type = "image/png"
        preprocess_result = None

    start_time = time.monotonic()

    # Gemini receives the (preprocessed or original) invoice image and
    # the extraction prompt only - no OCR hint. Exactly one Gemini call
    # per invoice.
    contents = [
        genai_types.Part.from_bytes(
            data=image_bytes,
            mime_type=image_mime_type,
        ),
        _EXTRACTION_PROMPT,
    ]

    # Key rotation: start from whichever key currently "works" (not
    # always Key 1 - a key stays active across every future invoice
    # until IT fails). On a failure that looks like the SAME key just
    # being overloaded or out of quota, the next key is tried silently,
    # in the same request, since a different Google account's key has
    # its own separate quota and is likely to just work. On any other
    # failure (a broken/invalid key, or a network problem reaching
    # Google at all), that is NOT retried with another key automatically
    # - it is surfaced right away, because: a broken key needs to be
    # noticed and fixed, not silently skipped past; and a network
    # problem reaching Google affects every key equally, so trying
    # another key would not help. Either way, the shared "active key"
    # pointer always moves to the NEXT key on any failure, so the next
    # attempt - whether that is the automatic silent one above, or the
    # store owner pressing "Try Again" after seeing an error - uses a
    # fresh key instead of repeating the one that just failed.
    global _active_key_index
    response = None
    last_exc = None
    key_index = _active_key_index % len(keys)
    for attempt_number in range(len(keys)):
        api_key = keys[key_index]
        client = _build_genai_client(api_key)
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=genai_types.GenerateContentConfig(
                    temperature=0,                       # deterministic reads (no random digit flips)
                    response_mime_type="application/json",
                    response_schema=_RESPONSE_SCHEMA,    # forces clean, complete JSON
                ),
            )
            _active_key_index = key_index  # this key worked - stay on it next time
            break
        except Exception as exc:
            last_exc = exc
            exc_str = str(exc).lower()
            is_overloaded_or_quota_error = (
                "unavailable" in exc_str or "503" in exc_str or "overloaded" in exc_str
                or "quota" in exc_str or "rate" in exc_str or "429" in exc_str
                or "resource_exhausted" in exc_str
            )
            key_index = (key_index + 1) % len(keys)
            _active_key_index = key_index  # move the shared pointer forward regardless of why this key failed
            if is_overloaded_or_quota_error and attempt_number < len(keys) - 1:
                continue
            break

    if response is None:
        exc = last_exc
        exc_str = str(exc).lower()

        # This call runs on Streamlit Cloud's server, not the store
        # owner's phone/laptop - so a failure here is NEVER actually
        # about the store owner's own internet connection, even when
        # Google's error text happens to contain the word "connection"
        # or "network" (Google uses that wording for its OWN outbound
        # problems too, e.g. an overloaded model or a blocked route out
        # of the server). The real Google error text is always appended,
        # in brackets, so the actual cause is visible instead of only
        # ever showing a guessed category.
        detail = f" [Google said: {exc}]"

        if "timeout" in exc_str or "deadline" in exc_str:
            raise GeminiAPIError(
                "The request to Gemini timed out." + detail
            ) from exc

        if "api key" in exc_str or "permission" in exc_str or "401" in exc_str or "403" in exc_str:
            raise GeminiAPIError(
                "Invalid or missing Gemini API key. "
                "Please check the GEMINI_API_KEY set for this app." + detail
            ) from exc

        if "quota" in exc_str or "rate" in exc_str or "429" in exc_str or "resource_exhausted" in exc_str:
            raise GeminiAPIError(
                "API quota/rate limit reached. Please wait a moment and try again." + detail
            ) from exc

        if "unavailable" in exc_str or "503" in exc_str or "overloaded" in exc_str:
            raise GeminiAPIError(
                "Gemini's servers are temporarily overloaded (this is on "
                "Google's side, not your connection). Please try again "
                "in a minute." + detail
            ) from exc

        if "network" in exc_str or "connection" in exc_str:
            raise GeminiAPIError(
                "Could not reach the Gemini API from the server. "
                "This is not about the phone/computer being used right "
                "now - it points to a problem reaching Google from where "
                "the app is hosted, or with the API key/project itself." + detail
            ) from exc

        raise GeminiAPIError(
            f"Gemini API error: {type(exc).__name__}." + detail
        ) from exc
    
    elapsed = round(time.monotonic() - start_time, 2)

    try:
        raw_text = response.text
    except Exception:
        raise OCRError(
            "Gemini returned an empty or blocked response. "
            "Please try with a different invoice image."
        )

    # Debug only (Phase 8.5): save the exact, unmodified raw Gemini
    # response - before any parsing/validation - into the same debug
    # session folder preprocessing already created. Never used by
    # production code; exists purely so a real regression can be
    # inspected against exactly what Gemini actually returned. Written
    # only when a debug_folder exists at all (i.e. DEBUG_PREPROCESSING
    # was on AND preprocessing succeeded enough to create one) - no
    # folder means nothing is written here, matching "only save files
    # that actually exist."

    medicines, invoice_header = _parse_combined_response(raw_text)
    medicines = _apply_quantity_formula(medicines)

    return {
        "medicines": medicines,
        "medicine_count": len(medicines),
        "extraction_time_seconds": elapsed,
        "model": GEMINI_MODEL,
        "invoice_header": invoice_header,
    }
