"""
Focused tests for the IQ200 extraction-only change:
  1. No OCR hint is sent to Gemini (single call, contents = [image, prompt]).
  2. Gemini is still called exactly once per invoice.
  3. The runtime prompt is the new prompt (adapted field names present).
  4. row_ocr / field_evidence are gone from the extraction path.
  5. qty/free stay separate fields; TQT formula behavior is unchanged.
  6. Row-to-column alignment / parsing behavior is unchanged (reuses
     existing _parse_and_validate_response, untouched).

All Gemini calls are mocked - no real API key, no network access.
Uses the same _build_genai_client patch seam as tests/test_ocr_service.py.
"""

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.invoice_scan import ocr_service
from modules.invoice_scan.ocr_service import (
    extract_medicines_from_file,
    MEDICINE_FIELDS,
    _EXTRACTION_PROMPT,
    _apply_quantity_formula,
)


def make_png_file_obj(name="invoice.png"):
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color=(180, 200, 220)).save(buf, format="PNG")
    data = buf.getvalue()
    mock = MagicMock()
    mock.name = name
    mock.size = len(data)
    mock.getvalue.return_value = data
    return mock


def valid_medicine_json(count=2):
    medicines = [
        {
            "name": f"Medicine {i}",
            "batch_number": f"B{i:03d}",
            "expiry_date": "06/2026",
            "qty": "10",
            "free": "1",
            "mrp": "25.00",
            "rate": "20.00",
            "gst_percent": "12",
        }
        for i in range(1, count + 1)
    ]
    return json.dumps(medicines)


class TestNoOcrHintSentToGemini:
    def test_contents_has_exactly_image_and_prompt(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = valid_medicine_json(1)
        mock_client.models.generate_content.return_value = mock_response

        with patch("modules.invoice_scan.ocr_service._build_genai_client",
                   return_value=mock_client):
            extract_medicines_from_file(make_png_file_obj())

        call_kwargs = mock_client.models.generate_content.call_args.kwargs
        contents = call_kwargs["contents"]
        assert len(contents) == 2, "contents must be [image, prompt] only - no OCR hint appended"
        assert contents[1] == _EXTRACTION_PROMPT

    def test_gemini_called_exactly_once(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = valid_medicine_json(1)
        mock_client.models.generate_content.return_value = mock_response

        with patch("modules.invoice_scan.ocr_service._build_genai_client",
                   return_value=mock_client):
            extract_medicines_from_file(make_png_file_obj())

        assert mock_client.models.generate_content.call_count == 1


class TestOcrHintPipelineRemoved:
    def test_row_ocr_module_no_longer_exists(self):
        with pytest.raises(ImportError):
            import modules.invoice_scan.row_ocr  # noqa: F401

    def test_field_evidence_module_no_longer_exists(self):
        with pytest.raises(ImportError):
            import modules.invoice_scan.field_evidence  # noqa: F401

    def test_ocr_service_has_no_ocr_hint_helpers(self):
        assert not hasattr(ocr_service, "_get_ocr_evidence")
        assert not hasattr(ocr_service, "_hint_text_from_evidence")
        assert not hasattr(ocr_service, "row_ocr")
        assert not hasattr(ocr_service, "field_evidence")

    def test_result_has_no_field_evidence_key(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = valid_medicine_json(1)
        mock_client.models.generate_content.return_value = mock_response

        with patch("modules.invoice_scan.ocr_service._build_genai_client",
                   return_value=mock_client):
            result = extract_medicines_from_file(make_png_file_obj())

        assert "_field_evidence" not in result["medicines"][0]


class TestNewPromptIsRuntimePrompt:
    def test_prompt_contains_new_field_definitions(self):
        assert 'value from the PRODUCT NAME / PRODUCT / ITEM NAME column' in _EXTRACTION_PROMPT
        assert 'value from the BATCH NO / BATCH column' in _EXTRACTION_PROMPT
        assert 'ROW INDEPENDENCE' not in _EXTRACTION_PROMPT  # old prompt's section header gone

    def test_prompt_does_not_reference_ocr_hint(self):
        assert "SECONDARY OCR HINT" not in _EXTRACTION_PROMPT
        assert "independent OCR engine" not in _EXTRACTION_PROMPT


class TestQtyFreeStaySeparateAndTqtFormulaUnchanged:
    def test_qty_and_free_are_distinct_fields(self):
        medicines = [{"qty": "10", "free": "2", "tqt": ""}]
        result = _apply_quantity_formula(medicines)
        assert result[0]["qty"] == "10"
        assert result[0]["free"] == "2"
        assert result[0]["quantity"] == "12"  # unchanged formula: qty + free

    def test_tqt_still_wins_when_present(self):
        medicines = [{"qty": "10", "free": "2", "tqt": "99"}]
        result = _apply_quantity_formula(medicines)
        assert result[0]["quantity"] == "99"

    def test_qty_only_when_no_free(self):
        medicines = [{"qty": "10", "free": "", "tqt": ""}]
        result = _apply_quantity_formula(medicines)
        assert result[0]["quantity"] == "10"

    def test_medicine_fields_schema_unchanged(self):
        # MEDICINE_FIELDS (internal schema) must remain untouched -
        # still includes "tqt" even though the new prompt no longer
        # asks Gemini to extract it (defaults to "" via existing
        # normalisation in _parse_and_validate_response).
        assert MEDICINE_FIELDS == [
            "name", "batch_number", "expiry_date",
            "qty", "free", "tqt", "mrp", "rate", "gst_percent",
        ]


class TestRowColumnAlignmentParsingUnchanged:
    def test_missing_tqt_in_gemini_response_defaults_blank(self, monkeypatch):
        # New prompt's JSON shape omits "tqt" - existing parser must
        # still default it to "" without breaking (untouched behavior).
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = valid_medicine_json(2)
        mock_client.models.generate_content.return_value = mock_response

        with patch("modules.invoice_scan.ocr_service._build_genai_client",
                   return_value=mock_client):
            result = extract_medicines_from_file(make_png_file_obj())

        assert len(result["medicines"]) == 2
        for row in result["medicines"]:
            assert row["tqt"] == ""
            assert row["name"] and row["batch_number"]
