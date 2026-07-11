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
from pathlib import Path

import google.genai as genai
from google.genai import types as genai_types
from dotenv import load_dotenv
from PIL import Image

from config.settings import GEMINI_MODEL, GEMINI_TIMEOUT_SECONDS
from core.exceptions import GeminiAPIError, OCRError
from utils.file_utils import get_image_preview, get_pdf_preview

# Load .env once at import time. No-op if key is already in environment
# (e.g. Streamlit Cloud injects secrets as env vars).
load_dotenv()

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

MEDICINE_FIELDS = [
    "name",
    "batch_number",
    "expiry_date",
    "quantity",
    "mrp",
    "rate",
    "gst_percent",
]

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = f"""
You are an invoice data extraction assistant for a medical store inventory system.

Your task is to extract ONLY the medicine / product line items from this invoice image.

═══════════════════════════════════════════════
ROW INDEPENDENCE — MOST CRITICAL RULE
═══════════════════════════════════════════════
Every medicine object in the JSON must contain ONLY values from its own physical row
in the invoice table.

NEVER copy, borrow, or shift any value from a neighbouring row — above or below.
NEVER merge two adjacent rows into one object.
NEVER use a Batch Number, Expiry, Quantity, Rate, or MRP from a different row.

Before returning the JSON, verify every object one final time:
  - Medicine Name, Batch Number, Expiry, Quantity, Rate, MRP and GST must all
    belong to the SAME physical row in the invoice table.
  - If any value was taken from a different row, correct it before returning.

═══════════════════════════════════════════════
BATCH NUMBER — CRITICAL ACCURACY RULES
═══════════════════════════════════════════════
The Batch Number is the most error-prone field. Follow these rules exactly:

1. Read the Batch Number ONLY from the "Batch No" column of the SAME row as the
   medicine name. Never take it from the row above or the row below.

2. Copy the batch number character by character exactly as printed:
   - Batch numbers may contain both letters AND digits (e.g. MPL254372, CN2175065, SPH251176).
   - Preserve every letter (uppercase and lowercase).
   - Preserve every digit.
   - Preserve every hyphen, slash or special character.
   - Never autocorrect spelling.
   - Never swap visually similar characters. Forbidden substitutions:
       O ↔ 0  (letter O vs digit zero)
       I ↔ 1  (letter I vs digit one)
       B ↔ 8  (letter B vs digit eight)
       S ↔ 5  (letter S vs digit five)
       Z ↔ 2  (letter Z vs digit two)
   - Never add, remove or rearrange characters.

3. If the batch number in a row is:
   - Partially obscured, smudged, or cut off → return ""
   - Unclear or low confidence → return ""
   - Completely missing from that row → return ""
   Never guess. Never infer. Return "" instead of a wrong value.

4. After reading all rows, scan your output for duplicate batch numbers that are
   adjacent (e.g. rows 3 and 4 both have "CN2175065"). This is almost certainly a
   row-shift error — re-check BOTH rows on the invoice image and correct the
   batch number before returning JSON.

═══════════════════════════════════════════════
GENERAL EXTRACTION RULES
═══════════════════════════════════════════════
1. Return ONLY a valid JSON array. No markdown, no backticks, no explanation.
2. Each element must be a JSON object with EXACTLY these keys:
   {json.dumps(MEDICINE_FIELDS)}
3. Extract ONLY medicine/product rows. Skip:
   - Invoice totals, subtotals, grand totals
   - GST summaries and tax breakdowns
   - Shipping or handling charges
   - Addresses, phone numbers, store names
   - Column headers or blank rows
4. If a field is not visible or not applicable, use an empty string "".
5. expiry_date: use the format found in the invoice (e.g. "03/2026" or "Mar-2026").
6. quantity: extract the number only (e.g. "10", not "10 strips").
7. mrp: extract the number only, no currency symbol.
8. Do NOT normalize, autocorrect or reformat medicine names or batch numbers.
   Return exactly what appears on the invoice.
9. If no medicines found, return: []
10. If the image is unreadable or not an invoice, return: []

═══════════════════════════════════════════════
FINAL VERIFICATION (do this before returning)
═══════════════════════════════════════════════
For every object in the array, confirm:
  ✓ Name, Batch Number, Expiry, Quantity, Rate, MRP, GST all come from the SAME row.
  ✓ No Batch Number was copied from an adjacent row.
  ✓ No adjacent objects share an identical Batch Number (unless the invoice itself
    genuinely shows the same batch number on two separate line items).
  ✓ No field was inferred, guessed, or autocompleted.

Example output (2 medicines — illustrative only, do not copy these values):
[
  {{"name": "Paracetamol 500mg", "batch_number": "MPL254372", "expiry_date": "06/2026",
    "quantity": "100", "mrp": "25.50", "rate": "20.00", "gst_percent": "12"}},
  {{"name": "Amoxicillin 250mg", "batch_number": "CN2175065", "expiry_date": "12/2025",
    "quantity": "50", "mrp": "85.00", "rate": "70.00", "gst_percent": "5"}}
]

Now extract all medicines from the invoice image provided.
"""

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
        3. Send to Gemini Vision with the JSON-only prompt.
        4. Parse and validate the response.
        5. Return a result dict (no DB writes).

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

    # Convert PIL Image to PNG bytes for the Gemini SDK.
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    image_bytes = buf.getvalue()

    client = _build_genai_client(api_key)

    start_time = time.monotonic()

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                genai_types.Part.from_bytes(
                    data=image_bytes,
                    mime_type="image/png",
                ),
                _EXTRACTION_PROMPT,
            ],
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
                "Gemini API rate limit reached. "
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

    medicines = _parse_and_validate_response(raw_text)

    return {
        "medicines": medicines,
        "medicine_count": len(medicines),
        "extraction_time_seconds": elapsed,
        "model": GEMINI_MODEL,
    }
