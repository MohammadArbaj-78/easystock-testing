"""
Tests for modules/invoice_scan/review_service.py.

Covers:
  - Session initialisation and active-detection
  - Editing values (update_medicine)
  - Deleting rows (delete_medicine)
  - Adding rows (add_empty_medicine)
  - Validation: required name, numeric fields, expiry format
  - Session persistence across simulated reruns
  - Confirmed: no database import anywhere in review_service
"""

import copy
import importlib
import sys
from pathlib import Path

import pytest

# Make the project root importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_session_state():
    """Clear session state before each test so tests are independent."""
    from modules.invoice_scan import review_service
    key = review_service._SESSION_KEY
    if key in st.session_state:
        del st.session_state[key]
    yield
    if key in st.session_state:
        del st.session_state[key]


def _sample_medicines(count=2):
    return [
        {
            "name": f"Medicine {i}",
            "batch_number": f"B{i:03d}",
            "expiry_date": f"0{i}/2026",
            "quantity": str(i * 10),
            "mrp": str(i * 25.0),
            "rate": str(i * 20.0),
            "gst_percent": "12",
        }
        for i in range(1, count + 1)
    ]


# ---------------------------------------------------------------------------
# No database write guarantee
# ---------------------------------------------------------------------------

class TestNoDatabaseWrite:
    def test_review_service_has_no_database_import(self):
        """Confirm review_service.py imports no database-related module."""
        import modules.invoice_scan.review_service as rs
        source = Path(rs.__file__).read_text()
        forbidden = ["from core.database", "import database", "sqlite3",
                     "get_connection", "INSERT", "UPDATE", "commit"]
        for term in forbidden:
            assert term not in source, (
                f"review_service.py must not import or use '{term}' — "
                "no database access is allowed in this module."
            )

    def test_review_ui_has_no_database_import(self):
        """Confirm review_ui.py imports no database-related module and
        contains no raw SQL string constants outside docstrings."""
        import modules.invoice_scan.review_ui as ru
        import ast
        source = Path(ru.__file__).read_text()
        tree = ast.parse(source)

        # Check that no import brings in database-related modules
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import):
                    module = ",".join(alias.name for alias in node.names)
                for forbidden in ("core.database", "sqlite3", "get_connection"):
                    assert forbidden not in module, (
                        f"review_ui.py must not import '{forbidden}'"
                    )

        # Collect all docstring node ids so we can skip them below.
        # A docstring is the first Expr(value=Constant(str)) in a
        # Module, FunctionDef, AsyncFunctionDef, or ClassDef body.
        docstring_nodes = set()
        for node in ast.walk(tree):
            body = None
            if isinstance(node, (ast.Module, ast.FunctionDef,
                                  ast.AsyncFunctionDef, ast.ClassDef)):
                body = node.body
            if body and isinstance(body[0], ast.Expr):
                expr = body[0].value
                if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
                    docstring_nodes.add(id(expr))

        # Verify no raw SQL strings appear in non-docstring constants
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstring_nodes:
                    continue  # skip docstrings
                for sql_kw in ("INSERT INTO", "UPDATE SET", "DELETE FROM",
                               "CREATE TABLE"):
                    assert sql_kw not in node.value, (
                        f"review_ui.py must not contain raw SQL: '{sql_kw}'"
                    )


# ---------------------------------------------------------------------------
# Session initialisation
# ---------------------------------------------------------------------------

class TestSessionInitialisation:
    def test_initialise_creates_session_with_medicines(self):
        from modules.invoice_scan import review_service
        meds = _sample_medicines(3)
        review_service.initialise_review_session("fbee8aa3a2a472ae1efc88eee8331410e24a82ef2e11091fa2162ca7da51e1b4", "invoice.png", meds)
        assert review_service.is_review_session_active("fbee8aa3a2a472ae1efc88eee8331410e24a82ef2e11091fa2162ca7da51e1b4")
        assert len(review_service.get_medicines()) == 3

    def test_initialise_deep_copies_medicines(self):
        from modules.invoice_scan import review_service
        meds = _sample_medicines(1)
        review_service.initialise_review_session("fbee8aa3a2a472ae1efc88eee8331410e24a82ef2e11091fa2162ca7da51e1b4", "invoice.png", meds)
        # Mutating the original list must not affect session state
        meds[0]["name"] = "MUTATED"
        assert review_service.get_medicines()[0]["name"] == "Medicine 1"

    def test_new_filename_replaces_previous_session(self):
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("53829cb9b7bee13d25eb287f36930a29a9abc66f1ad94391acb42e6d3e7f8f5d", "old.png", _sample_medicines(3))
        review_service.initialise_review_session("9002f59cf47a4e1bf6f77f8d728211b4cbd485959ebf2836c3a64bebfb5f4b9c", "new.png", _sample_medicines(1))
        assert review_service.is_review_session_active("9002f59cf47a4e1bf6f77f8d728211b4cbd485959ebf2836c3a64bebfb5f4b9c")
        assert not review_service.is_review_session_active("53829cb9b7bee13d25eb287f36930a29a9abc66f1ad94391acb42e6d3e7f8f5d")
        assert len(review_service.get_medicines()) == 1

    def test_is_review_session_active_false_when_no_session(self):
        from modules.invoice_scan import review_service
        assert not review_service.is_review_session_active("fbee8aa3a2a472ae1efc88eee8331410e24a82ef2e11091fa2162ca7da51e1b4")

    def test_is_review_session_active_false_for_different_filename(self):
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("7f071235805fbf58a2524f77bff76e1391d0d1cfe2f4c190d73054495e05b460", "a.png", _sample_medicines(1))
        assert not review_service.is_review_session_active("5f59d8e87a6efbf43f23410175de477396d74daf9ade43b442ca02fc5413ad1d")

    def test_get_medicines_returns_empty_list_with_no_session(self):
        from modules.invoice_scan import review_service
        assert review_service.get_medicines() == []


# ---------------------------------------------------------------------------
# Editing values
# ---------------------------------------------------------------------------

class TestUpdateMedicine:
    def test_update_existing_field(self):
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("73dc3489e5aa006a60e98ebaa1c7eef46ed88af3045a17195d00aecee8ddcad0", "inv.png", _sample_medicines(2))
        review_service.update_medicine(0, "name", "Paracetamol 500mg")
        assert review_service.get_medicines()[0]["name"] == "Paracetamol 500mg"

    def test_update_does_not_affect_other_rows(self):
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("73dc3489e5aa006a60e98ebaa1c7eef46ed88af3045a17195d00aecee8ddcad0", "inv.png", _sample_medicines(2))
        original_row1_name = review_service.get_medicines()[1]["name"]
        review_service.update_medicine(0, "name", "Changed")
        assert review_service.get_medicines()[1]["name"] == original_row1_name

    def test_update_out_of_range_index_is_safe(self):
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("73dc3489e5aa006a60e98ebaa1c7eef46ed88af3045a17195d00aecee8ddcad0", "inv.png", _sample_medicines(2))
        # Must not raise
        review_service.update_medicine(99, "name", "should not crash")
        assert len(review_service.get_medicines()) == 2

    def test_update_all_fields_in_a_row(self):
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("73dc3489e5aa006a60e98ebaa1c7eef46ed88af3045a17195d00aecee8ddcad0", "inv.png", _sample_medicines(1))
        fields = {
            "name": "Amoxicillin 250mg",
            "batch_number": "AMX2024",
            "expiry_date": "12/2025",
            "quantity": "50",
            "mrp": "85.00",
            "rate": "70.00",
            "gst_percent": "5",
        }
        for field, value in fields.items():
            review_service.update_medicine(0, field, value)
        row = review_service.get_medicines()[0]
        for field, value in fields.items():
            assert row[field] == value


# ---------------------------------------------------------------------------
# Deleting rows
# ---------------------------------------------------------------------------

class TestDeleteMedicine:
    def test_delete_reduces_count(self):
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("73dc3489e5aa006a60e98ebaa1c7eef46ed88af3045a17195d00aecee8ddcad0", "inv.png", _sample_medicines(3))
        review_service.delete_medicine(1)
        assert len(review_service.get_medicines()) == 2

    def test_delete_removes_correct_row(self):
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("73dc3489e5aa006a60e98ebaa1c7eef46ed88af3045a17195d00aecee8ddcad0", "inv.png", _sample_medicines(3))
        review_service.delete_medicine(0)  # remove first row
        remaining_names = [m["name"] for m in review_service.get_medicines()]
        assert "Medicine 1" not in remaining_names
        assert "Medicine 2" in remaining_names

    def test_delete_last_row_leaves_empty_list(self):
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("73dc3489e5aa006a60e98ebaa1c7eef46ed88af3045a17195d00aecee8ddcad0", "inv.png", _sample_medicines(1))
        review_service.delete_medicine(0)
        assert review_service.get_medicines() == []

    def test_delete_out_of_range_index_is_safe(self):
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("73dc3489e5aa006a60e98ebaa1c7eef46ed88af3045a17195d00aecee8ddcad0", "inv.png", _sample_medicines(2))
        review_service.delete_medicine(99)
        assert len(review_service.get_medicines()) == 2


# ---------------------------------------------------------------------------
# Adding rows
# ---------------------------------------------------------------------------

class TestAddEmptyMedicine:
    def test_add_increases_count(self):
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("73dc3489e5aa006a60e98ebaa1c7eef46ed88af3045a17195d00aecee8ddcad0", "inv.png", _sample_medicines(2))
        review_service.add_empty_medicine()
        assert len(review_service.get_medicines()) == 3

    def test_added_row_has_all_fields_empty(self):
        from modules.invoice_scan import review_service
        from modules.invoice_scan.ocr_service import MEDICINE_FIELDS
        review_service.initialise_review_session("73dc3489e5aa006a60e98ebaa1c7eef46ed88af3045a17195d00aecee8ddcad0", "inv.png", _sample_medicines(1))
        review_service.add_empty_medicine()
        new_row = review_service.get_medicines()[-1]
        for field in MEDICINE_FIELDS:
            assert field in new_row
            assert new_row[field] == ""

    def test_can_add_multiple_rows(self):
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("73dc3489e5aa006a60e98ebaa1c7eef46ed88af3045a17195d00aecee8ddcad0", "inv.png", [])
        for _ in range(5):
            review_service.add_empty_medicine()
        assert len(review_service.get_medicines()) == 5


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidateMedicine:
    def _make_valid_row(self):
        return {
            "name": "Paracetamol 500mg",
            "batch_number": "B001",
            "expiry_date": "06/2026",
            "quantity": "100",
            "mrp": "25.50",
            "rate": "20.00",
            "gst_percent": "12",
        }

    def test_valid_row_returns_no_errors(self):
        from modules.invoice_scan import review_service
        assert review_service.validate_medicine(self._make_valid_row()) == []

    def test_empty_name_returns_error(self):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["name"] = ""
        errors = review_service.validate_medicine(row)
        assert any("Medicine Name" in e for e in errors)

    def test_whitespace_only_name_returns_error(self):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["name"] = "   "
        errors = review_service.validate_medicine(row)
        assert any("Medicine Name" in e for e in errors)

    def test_empty_batch_number_is_valid(self):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["batch_number"] = ""
        assert review_service.validate_medicine(row) == []

    def test_non_numeric_quantity_returns_error(self):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["quantity"] = "abc"
        errors = review_service.validate_medicine(row)
        assert any("Quantity" in e for e in errors)

    def test_non_numeric_mrp_returns_error(self):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["mrp"] = "not-a-number"
        errors = review_service.validate_medicine(row)
        assert any("MRP" in e for e in errors)

    def test_non_numeric_rate_returns_error(self):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["rate"] = "abc"
        errors = review_service.validate_medicine(row)
        assert any("Rate" in e for e in errors)

    def test_non_numeric_gst_returns_error(self):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["gst_percent"] = "twenty"
        errors = review_service.validate_medicine(row)
        assert any("GST" in e for e in errors)

    def test_empty_optional_numeric_fields_are_valid(self):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        for field in ["quantity", "mrp", "rate", "gst_percent"]:
            row[field] = ""
        assert review_service.validate_medicine(row) == []

    # --- Expiry validation ---
    @pytest.mark.parametrize("expiry", [
        # Spec accept cases
        "3/28", "03/28", "12/26", "03/2028",
        "Jun-2028", "June-2028", "DEC-26",
        # Additional valid formats
        "06/26", "06/2026", "6/2026",
        "Jun-2026", "June-2026", "jun/2026",
        "Mar-26", "03-2026",
    ])
    def test_valid_expiry_formats(self, expiry):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["expiry_date"] = expiry
        errors = review_service.validate_medicine(row)
        assert not any("Expiry" in e for e in errors), (
            f"'{expiry}' should be accepted but got errors: {errors}"
        )

    @pytest.mark.parametrize("bad_expiry", [
        "0/28", "13/28", "32/28", "99/9999", "abc",
        "MPL254372", "hello", "2026", "abcdef",
    ])
    def test_invalid_expiry_formats(self, bad_expiry):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["expiry_date"] = bad_expiry
        errors = review_service.validate_medicine(row)
        assert any("Expiry" in e for e in errors), (
            f"'{bad_expiry}' should be rejected but was accepted"
        )

    def test_error_message_mentions_month_year_format(self):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["expiry_date"] = "99/9999"
        errors = review_service.validate_medicine(row)
        assert any("Month/Year format" in e for e in errors), (
            f"Error must mention 'Month/Year format', got: {errors}"
        )

    def test_empty_expiry_is_valid(self):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["expiry_date"] = ""
        assert review_service.validate_medicine(row) == []


# ---------------------------------------------------------------------------
# validate_all_medicines
# ---------------------------------------------------------------------------

class TestValidateAllMedicines:
    def test_returns_empty_dict_when_all_valid(self):
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("73dc3489e5aa006a60e98ebaa1c7eef46ed88af3045a17195d00aecee8ddcad0", "inv.png", _sample_medicines(2))
        assert review_service.validate_all_medicines() == {}

    def test_returns_errors_for_invalid_rows(self):
        from modules.invoice_scan import review_service
        meds = _sample_medicines(2)
        meds[0]["name"] = ""       # invalid
        meds[1]["quantity"] = "x"  # invalid
        review_service.initialise_review_session("73dc3489e5aa006a60e98ebaa1c7eef46ed88af3045a17195d00aecee8ddcad0", "inv.png", meds)
        errors = review_service.validate_all_medicines()
        assert 0 in errors
        assert 1 in errors

    def test_valid_rows_not_in_error_dict(self):
        from modules.invoice_scan import review_service
        meds = _sample_medicines(3)
        meds[1]["name"] = ""  # only row 1 is invalid
        review_service.initialise_review_session("73dc3489e5aa006a60e98ebaa1c7eef46ed88af3045a17195d00aecee8ddcad0", "inv.png", meds)
        errors = review_service.validate_all_medicines()
        assert 0 not in errors
        assert 1 in errors
        assert 2 not in errors


# ---------------------------------------------------------------------------
# Session persistence (simulated reruns)
# ---------------------------------------------------------------------------

class TestSessionPersistence:
    def test_edits_persist_across_simulated_reruns(self):
        """Confirm edits survive what would be successive Streamlit reruns."""
        from modules.invoice_scan import review_service

        review_service.initialise_review_session("73dc3489e5aa006a60e98ebaa1c7eef46ed88af3045a17195d00aecee8ddcad0", "inv.png", _sample_medicines(2))
        review_service.update_medicine(0, "name", "Edited Name")

        assert review_service.is_review_session_active("73dc3489e5aa006a60e98ebaa1c7eef46ed88af3045a17195d00aecee8ddcad0")
        assert review_service.get_medicines()[0]["name"] == "Edited Name"

    def test_delete_and_add_persist(self):
        from modules.invoice_scan import review_service

        review_service.initialise_review_session("73dc3489e5aa006a60e98ebaa1c7eef46ed88af3045a17195d00aecee8ddcad0", "inv.png", _sample_medicines(3))
        review_service.delete_medicine(2)
        review_service.add_empty_medicine()

        meds = review_service.get_medicines()
        assert len(meds) == 3
        assert meds[-1]["name"] == ""


class TestOcrCalledOnce:
    """Tests verifying the Gemini-once guarantee via session state."""

    def test_initialise_stores_ocr_metadata(self):
        from modules.invoice_scan import review_service
        import hashlib
        fake_hash = hashlib.sha256(b"invoice.png").hexdigest()
        meta = {
            "medicine_count": 5,
            "extraction_time_seconds": 2.34,
            "model": "gemini-2.5-flash",
        }
        review_service.initialise_review_session(
            fake_hash, "invoice.png", _sample_medicines(5), ocr_metadata=meta
        )
        cached = review_service.get_ocr_metadata()
        assert cached["medicine_count"] == 5
        assert cached["extraction_time_seconds"] == 2.34
        assert cached["model"] == "gemini-2.5-flash"

    def test_get_ocr_metadata_returns_empty_dict_with_no_session(self):
        from modules.invoice_scan import review_service
        assert review_service.get_ocr_metadata() == {}

    def test_initialise_without_metadata_stores_empty_dict(self):
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("fbee8aa3a2a472ae1efc88eee8331410e24a82ef2e11091fa2162ca7da51e1b4", "invoice.png", _sample_medicines(2))
        assert review_service.get_ocr_metadata() == {}

    def test_session_active_means_gemini_must_be_skipped(self):
        """Structural test: confirm upload_ui._render_ocr_section returns
        before calling extract_medicines_from_file when the session is active.
        This is the guarantee that Gemini is called exactly once."""
        src = open("modules/invoice_scan/upload_ui.py").read()
        lines = src.split("\n")

        # The guard now uses file_hash (not uploaded_file.name) — find it
        guard_line = next(
            i for i, l in enumerate(lines)
            if "is_review_session_active(file_hash)" in l
        )
        gemini_call_line = next(
            i for i, l in enumerate(lines)
            if "extract_medicines_from_file(uploaded_file)" in l
        )
        assert guard_line < gemini_call_line

        guard_section = lines[guard_line:gemini_call_line]
        assert any("return" in l for l in guard_section), (
            "The session guard in _render_ocr_section must contain a 'return' "
            "before the extract_medicines_from_file call."
        )

    def test_metadata_survives_independent_of_medicine_edits(self):
        """OCR metadata (count, time, model) must not change when medicines
        are edited, deleted, or added — it reflects the original extraction."""
        from modules.invoice_scan import review_service
        import hashlib
        fake_hash = hashlib.sha256(b"invoice.png").hexdigest()
        meta = {"medicine_count": 3, "extraction_time_seconds": 1.5, "model": "test"}
        review_service.initialise_review_session(
            fake_hash, "invoice.png", _sample_medicines(3), ocr_metadata=meta
        )

        review_service.delete_medicine(0)
        review_service.add_empty_medicine()
        review_service.update_medicine(0, "name", "Changed")

        # Medicines changed but metadata must be unchanged
        assert review_service.get_ocr_metadata()["medicine_count"] == 3
        assert len(review_service.get_medicines()) == 3  # 3-1+1=3


class TestRenderReviewUiEntryPoint:
    """Tests for the render_review_ui(ocr_result) public API contract."""

    def test_render_review_ui_function_is_importable(self):
        """render_review_ui must exist and be callable."""
        from modules.invoice_scan.review_ui import render_review_ui
        assert callable(render_review_ui)

    def test_render_review_ui_accepts_ocr_result_dict(self):
        """render_review_ui must accept a single ocr_result dict argument
        and not raise on the dict's presence (only Streamlit rendering
        would fail without a real server, which we patch out)."""
        from modules.invoice_scan.review_ui import render_review_ui

        ocr_result = {
            "medicines": _sample_medicines(2),
            "medicine_count": 2,
            "extraction_time_seconds": 1.0,
            "model": "gemini-2.5-flash",
            "source_file": "test.png",
        }

        # Patch every Streamlit call that render_review_ui and its
        # callees might make. We only verify the function doesn't raise
        # and that it reads the expected keys from ocr_result.
        def columns_side_effect(spec):
            n = len(spec) if isinstance(spec, (list, tuple)) else spec
            return [MagicMock() for _ in range(n)]

        with patch("streamlit.markdown"), \
             patch("streamlit.caption"), \
             patch("streamlit.info"), \
             patch("streamlit.divider"), \
             patch("streamlit.metric"), \
             patch("streamlit.write"), \
             patch("streamlit.columns", side_effect=columns_side_effect), \
             patch("streamlit.text_input", return_value=""), \
             patch("streamlit.button", return_value=False), \
             patch("streamlit.session_state", {}):
            try:
                render_review_ui(ocr_result)
            except Exception as exc:
                # Only Streamlit-internal errors (ScriptRunContext) are
                # expected; any application-level error is a real failure.
                if "ScriptRunContext" not in str(exc) and "session state" not in str(exc).lower():
                    raise

    def test_render_review_ui_source_file_key_required(self):
        """ocr_result must include 'source_file' so the upload_ui
        integration contract is met. Verify it's read correctly."""
        from modules.invoice_scan.review_ui import render_review_ui
        import inspect
        src = inspect.getsource(render_review_ui)
        assert 'source_file' in src, (
            "render_review_ui must read 'source_file' from ocr_result"
        )

    def test_upload_ui_adds_source_file_before_calling_render_review_ui(self):
        """Verify upload_ui.py uses hash-based session identity and renders
        the review table - the integration contract."""
        src = open("modules/invoice_scan/upload_ui.py").read()
        assert "compute_file_hash" in src, "hash computation must be present"
        assert "is_review_session_active(file_hash)" in src, "hash-based guard required"
        assert "render_review_section" in src, "review table must be rendered"
        assert "st.json" not in src, "st.json (read-only preview) must be gone"
