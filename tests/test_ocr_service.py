"""
Tests for modules/invoice_scan/ocr_service.py.

All Gemini API calls are mocked — no real API key, no network access.
Tests verify:
  - Successful extraction from image and PDF
  - Corrupt/unreadable PDF handling
  - Invalid image handling
  - Gemini timeout
  - Invalid API key
  - Invalid JSON response
  - Empty extraction (Gemini returns [])
  - Missing API key
  - Response JSON parsing edge cases (markdown fences, missing fields)
"""

import io
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

# Ensure test can import the project modules from project root
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.exceptions import GeminiAPIError, OCRError
from modules.invoice_scan.ocr_service import (
    _get_api_key,
    _parse_and_validate_response,
    _file_to_pil_image,
    _build_genai_client,
    extract_medicines_from_file,
    MEDICINE_FIELDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_png_file_obj(name="invoice.png", width=100, height=100):
    """Return a minimal mock UploadedFile for a PNG."""
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(180, 200, 220)).save(buf, format="PNG")
    data = buf.getvalue()

    mock = MagicMock()
    mock.name = name
    mock.size = len(data)
    mock.getvalue.return_value = data
    return mock


def make_pdf_file_obj(name="invoice.pdf", valid=True):
    """Return a minimal mock UploadedFile for a PDF.

    valid=True  → a real minimal PDF that PyMuPDF can rasterize.
    valid=False → corrupt bytes that PyMuPDF will fail on.
    """
    if valid:
        data = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj
xref
0 4
0000000000 65535 f\r
0000000009 00000 n\r
0000000058 00000 n\r
0000000115 00000 n\r
trailer<</Size 4/Root 1 0 R>>
startxref
190
%%EOF"""
    else:
        data = b"NOT A PDF AT ALL - CORRUPT"

    mock = MagicMock()
    mock.name = name
    mock.size = len(data)
    mock.getvalue.return_value = data
    return mock


def make_corrupt_image_obj(name="bad.png"):
    """Return a mock whose bytes are not a valid image."""
    mock = MagicMock()
    mock.name = name
    mock.size = 42
    mock.getvalue.return_value = b"this is not an image"
    return mock


def valid_medicine_json(count=2):
    """Return a JSON string matching the expected schema."""
    medicines = [
        {
            "name": f"Medicine {i}",
            "batch_number": f"B{i:03d}",
            "expiry_date": "06/2026",
            "quantity": "50",
            "mrp": "25.00",
            "rate": "20.00",
            "gst_percent": "12",
        }
        for i in range(1, count + 1)
    ]
    return json.dumps(medicines)


def mock_gemini_response(text):
    """Return a mock Gemini response object whose .text property returns text."""
    resp = MagicMock()
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# Unit tests: _get_api_key
# ---------------------------------------------------------------------------

class TestGetApiKey:
    def test_reads_key_from_environment(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key-abc")
        assert _get_api_key() == "test-key-abc"

    def test_raises_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(GeminiAPIError, match="Gemini API key not found"):
            _get_api_key()

    def test_raises_when_key_empty_string(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "   ")
        with pytest.raises(GeminiAPIError, match="Gemini API key not found"):
            _get_api_key()


# ---------------------------------------------------------------------------
# Unit tests: _parse_and_validate_response
# ---------------------------------------------------------------------------

class TestParseAndValidateResponse:
    def test_parses_valid_json_array(self):
        result = _parse_and_validate_response(valid_medicine_json(2))
        assert len(result) == 2
        assert result[0]["name"] == "Medicine 1"

    def test_all_medicine_fields_present_in_each_row(self):
        result = _parse_and_validate_response(valid_medicine_json(1))
        for field in MEDICINE_FIELDS:
            assert field in result[0]

    def test_empty_array_returns_empty_list(self):
        result = _parse_and_validate_response("[]")
        assert result == []

    def test_strips_markdown_fences(self):
        raw = "```json\n" + valid_medicine_json(1) + "\n```"
        result = _parse_and_validate_response(raw)
        assert len(result) == 1

    def test_strips_plain_code_fences(self):
        raw = "```\n" + valid_medicine_json(1) + "\n```"
        result = _parse_and_validate_response(raw)
        assert len(result) == 1

    def test_raises_ocr_error_on_invalid_json(self):
        with pytest.raises(OCRError, match="could not be parsed as JSON"):
            _parse_and_validate_response("this is not json at all")

    def test_raises_ocr_error_when_not_a_list(self):
        with pytest.raises(OCRError, match="unexpected response format"):
            _parse_and_validate_response('{"name": "single object not list"}')

    def test_drops_rows_with_empty_name(self):
        data = json.dumps([
            {"name": "", "batch_number": "B001", "expiry_date": "", "quantity": "",
             "mrp": "", "rate": "", "gst_percent": ""},
            {"name": "Real Medicine", "batch_number": "B002", "expiry_date": "01/2027",
             "quantity": "10", "mrp": "50", "rate": "40", "gst_percent": "5"},
        ])
        result = _parse_and_validate_response(data)
        assert len(result) == 1
        assert result[0]["name"] == "Real Medicine"

    def test_fills_missing_fields_with_empty_string(self):
        # Gemini returns a row missing some fields
        data = json.dumps([{"name": "Partial Med"}])
        result = _parse_and_validate_response(data)
        assert len(result) == 1
        for field in MEDICINE_FIELDS:
            assert field in result[0]
            assert isinstance(result[0][field], str)

    def test_drops_non_dict_rows(self):
        data = json.dumps(["not a dict", {"name": "Real Med", "batch_number": "B1",
            "expiry_date": "", "quantity": "", "mrp": "", "rate": "", "gst_percent": ""}])
        result = _parse_and_validate_response(data)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Unit tests: _file_to_pil_image
# ---------------------------------------------------------------------------

class TestFileToPilImage:
    def test_converts_png_file_to_image(self):
        f = make_png_file_obj()
        img = _file_to_pil_image(f)
        assert isinstance(img, Image.Image)

    def test_raises_ocr_error_on_corrupt_image(self):
        f = make_corrupt_image_obj()
        with pytest.raises(OCRError, match="Could not read"):
            _file_to_pil_image(f)

    def test_converts_valid_pdf_first_page(self):
        f = make_pdf_file_obj(valid=True)
        img = _file_to_pil_image(f)
        assert isinstance(img, Image.Image)

    def test_raises_ocr_error_on_corrupt_pdf(self):
        f = make_pdf_file_obj(valid=False)
        with pytest.raises(OCRError, match="Could not read this PDF"):
            _file_to_pil_image(f)


# ---------------------------------------------------------------------------
# Integration tests: extract_medicines_from_file (Gemini mocked)
# ---------------------------------------------------------------------------

class TestExtractMedicinesFromFile:
    """Integration tests for extract_medicines_from_file.

    All Gemini API calls are mocked via _build_genai_client, which is
    the cleanest patchable seam: it's a module-level function whose return
    value (a client object) controls all downstream API behavior. No need
    to patch the entire google.genai module or deal with gRPC initialization.
    """

    def _make_mock_client(self, response_text):
        """Return a mock genai.Client whose generate_content returns response_text."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = response_text
        mock_client.models.generate_content.return_value = mock_response
        return mock_client

    def _make_mock_client_raising(self, exception):
        """Return a mock client whose generate_content raises exception."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = exception
        return mock_client

    def test_successful_extraction_from_image(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        mock_client = self._make_mock_client(valid_medicine_json(3))

        with patch("modules.invoice_scan.ocr_service._build_genai_client",
                   return_value=mock_client):
            result = extract_medicines_from_file(make_png_file_obj())

        assert result["medicine_count"] == 3
        assert len(result["medicines"]) == 3
        assert isinstance(result["extraction_time_seconds"], float)
        assert result["model"] is not None

    def test_successful_extraction_from_pdf(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        mock_client = self._make_mock_client(valid_medicine_json(1))

        with patch("modules.invoice_scan.ocr_service._build_genai_client",
                   return_value=mock_client):
            result = extract_medicines_from_file(make_pdf_file_obj(valid=True))

        assert result["medicine_count"] == 1

    def test_corrupt_pdf_raises_ocr_error(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        # No mock needed — fails before reaching Gemini
        with pytest.raises(OCRError, match="Could not read this PDF"):
            extract_medicines_from_file(make_pdf_file_obj(valid=False))

    def test_corrupt_image_raises_ocr_error(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        with pytest.raises(OCRError, match="Could not read"):
            extract_medicines_from_file(make_corrupt_image_obj())

    def test_missing_api_key_raises_gemini_api_error(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(GeminiAPIError, match="API key not found"):
            extract_medicines_from_file(make_png_file_obj())

    def test_gemini_timeout_raises_gemini_api_error(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        mock_client = self._make_mock_client_raising(
            Exception("504 Deadline exceeded: timeout")
        )
        with patch("modules.invoice_scan.ocr_service._build_genai_client",
                   return_value=mock_client):
            with pytest.raises(GeminiAPIError, match="timed out"):
                extract_medicines_from_file(make_png_file_obj())

    def test_invalid_api_key_raises_gemini_api_error(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "bad-key")
        mock_client = self._make_mock_client_raising(
            Exception("401 API key not valid. Please pass a valid API key.")
        )
        with patch("modules.invoice_scan.ocr_service._build_genai_client",
                   return_value=mock_client):
            with pytest.raises(GeminiAPIError, match="Invalid or missing Gemini API key"):
                extract_medicines_from_file(make_png_file_obj())

    def test_rate_limit_raises_gemini_api_error(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        mock_client = self._make_mock_client_raising(
            Exception("429 Resource exhausted: quota exceeded")
        )
        with patch("modules.invoice_scan.ocr_service._build_genai_client",
                   return_value=mock_client):
            with pytest.raises(GeminiAPIError, match="rate limit"):
                extract_medicines_from_file(make_png_file_obj())

    def test_invalid_json_response_raises_ocr_error(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        mock_client = self._make_mock_client(
            "I found these medicines on the invoice: Paracetamol, Amoxicillin"
        )
        with patch("modules.invoice_scan.ocr_service._build_genai_client",
                   return_value=mock_client):
            with pytest.raises(OCRError, match="could not be parsed as JSON"):
                extract_medicines_from_file(make_png_file_obj())

    def test_empty_extraction_returns_empty_list(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        mock_client = self._make_mock_client("[]")

        with patch("modules.invoice_scan.ocr_service._build_genai_client",
                   return_value=mock_client):
            result = extract_medicines_from_file(make_png_file_obj())

        assert result["medicine_count"] == 0
        assert result["medicines"] == []

    def test_result_contains_all_required_keys(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        mock_client = self._make_mock_client(valid_medicine_json(1))

        with patch("modules.invoice_scan.ocr_service._build_genai_client",
                   return_value=mock_client):
            result = extract_medicines_from_file(make_png_file_obj())

        assert "medicines" in result
        assert "medicine_count" in result
        assert "extraction_time_seconds" in result
        assert "model" in result
