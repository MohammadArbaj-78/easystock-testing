"""
Invoice OCR extraction service using Gemini Vision.

This is the only file added by Module 3 (OCR). Narrow scope:
  - Read the API key from environment (never hardcoded).
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

Return ONLY valid JSON, no markdown, no commentary. Return a single JSON array (not an object), one element per medicine row, with EXACTLY these keys per object:
{json.dumps(_PROMPT_FIELDS)}

If no medicines are found, or the image is unreadable / not an invoice, return: []
"""

# Forces Gemini to return clean, complete JSON matching exactly these 8 keys.
# This (not the prompt text) is what kills bad-JSON / missing-field failures.
_RESPONSE_SCHEMA = genai_types.Schema(
    type=genai_types.Type.ARRAY,
    items=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={f: genai_types.Schema(type=genai_types.Type.STRING) for f in _PROMPT_FIELDS},
        required=list(_PROMPT_FIELDS),
        property_ordering=list(_PROMPT_FIELDS),
    ),
)

# ---------------------------------------------------------------------------
# Key loading
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    """Read the Gemini API key from the environment.

    Raises:
        GeminiAPIError: If the key is absent or empty.
    """
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise GeminiAPIError(
            "Gemini API key not found. "
            "Please add GEMINI_API_KEY to your .env file and restart the app."
        )
    return key

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

    valid_rows = []
    for row in parsed:
        if not isinstance(row, dict):
            continue
        normalised = {field: str(row.get(field, "")).strip() for field in MEDICINE_FIELDS}
        if not normalised["name"]:
            continue
        valid_rows.append(normalised)

    return valid_rows

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
    api_key = _get_api_key()
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

    client = _build_genai_client(api_key)

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
    except Exception as exc:
        exc_str = str(exc).lower()

        if "timeout" in exc_str or "deadline" in exc_str:
            raise GeminiAPIError(
                "The request to Gemini timed out. "
                "Please check your internet connection and try again."
            ) from exc

        if "api key" in exc_str or "permission" in exc_str or "401" in exc_str or "403" in exc_str:
            raise GeminiAPIError(
                "Invalid or missing Gemini API key. "
                "Please check your GEMINI_API_KEY in the .env file."
            ) from exc

        if "quota" in exc_str or "rate" in exc_str or "429" in exc_str:
            raise GeminiAPIError(
                f"API quota/rate limit error: {exc}. "
                "Please wait a moment and try again."
            ) from exc

        if "network" in exc_str or "connection" in exc_str or "unavailable" in exc_str:
            raise GeminiAPIError(
                "Could not reach the Gemini API. "
                "Please check your internet connection and try again."
            ) from exc

        raise GeminiAPIError(
            f"Gemini API error: {type(exc).__name__}. Please try again."
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

    medicines = _parse_and_validate_response(raw_text)
    medicines = _apply_quantity_formula(medicines)

    return {
        "medicines": medicines,
        "medicine_count": len(medicines),
        "extraction_time_seconds": elapsed,
        "model": GEMINI_MODEL,
    }
