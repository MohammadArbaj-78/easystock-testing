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
        # Message wording was rewritten (Warnings sprint, v2.13.5) to
        # "Medicine name is required." - was "Medicine Name cannot be
        # empty." Check case-insensitively for the field + "required"
        # rather than the old exact substring.
        assert any("medicine name" in e.lower() and "required" in e.lower() for e in errors), (
            f"Expected a 'Medicine name is required' error, got: {errors}"
        )

    def test_whitespace_only_name_returns_error(self):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["name"] = "   "
        errors = review_service.validate_medicine(row)
        assert any("medicine name" in e.lower() and "required" in e.lower() for e in errors), (
            f"Expected a 'Medicine name is required' error, got: {errors}"
        )

    def test_empty_batch_number_is_blocking(self):
        # RED-validation sprint (v2.13.5): Batch Number was previously
        # optional (blank was valid). It is now required, same as the
        # other six fields - this test previously asserted the OLD
        # optional behavior ("...is_valid", expecting []) and was stale
        # since that sprint shipped. Renamed and rewritten to assert
        # the current, intended behavior: blank batch blocks Save.
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["batch_number"] = ""
        errors = review_service.validate_medicine(row)
        assert any("batch number" in e.lower() and "required" in e.lower() for e in errors), (
            f"Expected a 'Batch number is required' error, got: {errors}"
        )

    def test_non_numeric_quantity_returns_error(self):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["quantity"] = "abc"
        errors = review_service.validate_medicine(row)
        # Message wording rewritten (Warnings sprint) to "Enter a valid
        # quantity." - was "...Quantity...". Case-insensitive field check.
        assert any("quantity" in e.lower() for e in errors)

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
        # Message wording rewritten (Warnings sprint) to "Enter a valid
        # rate." - was "...Rate...". Case-insensitive field check.
        assert any("rate" in e.lower() for e in errors)

    def test_non_numeric_gst_returns_error(self):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["gst_percent"] = "twenty"
        errors = review_service.validate_medicine(row)
        assert any("GST" in e for e in errors)

    def test_empty_required_numeric_fields_are_blocking(self):
        # Stabilization sprint (P0 Validation Consistency): Quantity,
        # MRP, Rate, and GST % are required fields - a blank value must
        # always be a blocking error, never silently valid. Previously
        # these were only checked "if present, must be numeric", which
        # let a blank required field slip through with no error at all.
        #
        # Message wording was later rewritten (Warnings sprint, v2.13.5)
        # from "X cannot be empty" to "X is required." - this test's
        # substring checks are updated to match; the field coverage and
        # required-ness being asserted are unchanged.
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        for field in ["quantity", "mrp", "rate", "gst_percent"]:
            row[field] = ""
        errors = review_service.validate_medicine(row)
        assert len(errors) == 4, f"Expected exactly 4 blocking errors, got: {errors}"
        for label in ["Quantity", "MRP", "Rate", "GST"]:
            assert any(label in e and "required" in e for e in errors), (
                f"Expected a 'required' error mentioning {label}, got: {errors}"
            )

    def test_empty_quantity_alone_is_blocking(self):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["quantity"] = ""
        errors = review_service.validate_medicine(row)
        assert any("Quantity is required" in e for e in errors)

    def test_empty_mrp_alone_is_blocking(self):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["mrp"] = ""
        errors = review_service.validate_medicine(row)
        assert any("MRP is required" in e for e in errors)

    def test_empty_rate_alone_is_blocking(self):
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["rate"] = ""
        errors = review_service.validate_medicine(row)
        assert any("Rate is required" in e for e in errors)

    def test_empty_gst_alone_is_blocking(self):
        # Stabilization sprint: this is the specific "GST empty sometimes
        # is not treated as blocking" bug reported for this sprint.
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["gst_percent"] = ""
        errors = review_service.validate_medicine(row)
        assert any("GST is required" in e for e in errors)

    def test_fully_empty_row_is_blocking_on_every_required_field(self):
        # Stabilization sprint: a freshly "Add New Medicine"-d row (every
        # field blank) must always produce a blocking error - this is
        # the "empty medicine rows sometimes do not receive the expected
        # red highlight" bug reported for this sprint.
        #
        # RED-validation sprint (v2.13.5, later): Batch Number and
        # Expiry became required too (previously optional) - all 7
        # fields are now required, not 5. Updated from the old
        # "5 blocking errors" expectation to match.
        from modules.invoice_scan import review_service
        row = {"name": "", "batch_number": "", "expiry_date": "",
               "quantity": "", "mrp": "", "rate": "", "gst_percent": ""}
        errors = review_service.validate_medicine(row)
        # All 7 fields (Medicine Name, Batch Number, Expiry, Quantity,
        # MRP, Rate, GST %) are required as of v2.13.5.
        assert len(errors) == 7, f"Expected exactly 7 blocking errors, got: {errors}"

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
        # Message wording rewritten (Warnings sprint) to "Enter a valid
        # expiry date." (lowercase 'expiry', mid-sentence) - was
        # "...Expiry...". Case-insensitive field check; underlying
        # is_valid_expiry() rejection logic itself is unchanged and
        # directly confirmed correct for every one of these values.
        assert any("expiry" in e.lower() for e in errors), (
            f"'{bad_expiry}' should be rejected but was accepted"
        )

    def test_error_message_mentions_expected_format_in_review_ui(self):
        # Originally named test_error_message_mentions_month_year_format
        # and checked review_service.validate_medicine()'s raw return
        # value for "Month/Year format" text. That text has never lived
        # in validate_medicine() - it is a review_ui.py-only display
        # enrichment (_BLOCKING_FIELD_INFO), added when a RED error is
        # rendered to the store owner. The test was checking the wrong
        # layer. Retargeted to check where this guidance actually lives
        # today, preserving the original intent (the store owner must
        # be told the expected expiry format) without weakening it.
        from modules.invoice_scan import review_ui
        expiry_entries = [
            entry for entry in review_ui._BLOCKING_FIELD_INFO
            if entry[1] == "expiry_date"
        ]
        assert expiry_entries, "No _BLOCKING_FIELD_INFO entries for expiry_date"
        assert all("MM/YY" in entry[2] or "Month" in entry[2] for entry in expiry_entries), (
            f"Expected expiry_date entries to state the accepted format, got: {expiry_entries}"
        )

    def test_empty_expiry_is_blocking(self):
        # RED-validation sprint (v2.13.5): Expiry was previously optional
        # (blank was valid; only an invalid *format* blocked Save). It is
        # now required, same as the other six fields - this test
        # previously asserted the OLD optional behavior ("...is_valid",
        # expecting []) and was stale since that sprint shipped. Renamed
        # and rewritten to assert the current, intended behavior: blank
        # expiry blocks Save.
        from modules.invoice_scan import review_service
        row = self._make_valid_row()
        row["expiry_date"] = ""
        errors = review_service.validate_medicine(row)
        assert any("expiry" in e.lower() and "required" in e.lower() for e in errors), (
            f"Expected an 'Expiry is required' error, got: {errors}"
        )


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


# ---------------------------------------------------------------------------
# Stabilization sprint (P0): Review Session Lifecycle
# ---------------------------------------------------------------------------

class TestClearSessionAndReset:
    """clear_session() and reset_session_for_new_upload() must both fully
    tear down a review session and every per-row widget key - the two
    functions differ only in whether they also reset the file_uploader
    widget's own key (clear_session() does, for the explicit "Clear
    Review" button; reset_session_for_new_upload() does not, since it
    runs in the same script run where the uploader is already
    instantiated with a new file)."""

    def test_clear_session_removes_session_dict(self):
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("h1", "inv.jpg", _sample_medicines(2))
        assert review_service.has_any_session() is True
        review_service.clear_session()
        assert review_service.has_any_session() is False

    def test_clear_session_removes_row_widget_keys(self):
        import streamlit as st
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("h1", "inv.jpg", _sample_medicines(1))
        row_id = review_service.get_medicines()[0]["_row_id"]
        st.session_state[f"review_row_{row_id}_name"] = "edited"
        st.session_state[f"delete_row_{row_id}"] = False
        review_service.clear_session()
        assert f"review_row_{row_id}_name" not in st.session_state
        assert f"delete_row_{row_id}" not in st.session_state

    def test_clear_session_removes_uploader_key(self):
        import streamlit as st
        from modules.invoice_scan import review_service
        st.session_state["invoice_file_uploader"] = "sentinel"
        review_service.clear_session()
        assert "invoice_file_uploader" not in st.session_state

    def test_reset_for_new_upload_removes_session_dict(self):
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("h1", "inv.jpg", _sample_medicines(2))
        review_service.reset_session_for_new_upload()
        assert review_service.has_any_session() is False

    def test_reset_for_new_upload_removes_row_widget_keys_both_prefixes(self):
        import streamlit as st
        from modules.invoice_scan import review_service
        review_service.initialise_review_session("h1", "inv.jpg", _sample_medicines(1))
        row_id = review_service.get_medicines()[0]["_row_id"]
        st.session_state[f"review_row_{row_id}_name"] = "edited"
        st.session_state[f"delete_row_{row_id}"] = False
        review_service.reset_session_for_new_upload()
        assert f"review_row_{row_id}_name" not in st.session_state
        assert f"delete_row_{row_id}" not in st.session_state

    def test_reset_for_new_upload_does_not_touch_uploader_key(self):
        # This is the core Sprint 2.1 fix: the automatic new-upload reset
        # must never fight the file_uploader widget's own key while it is
        # already instantiated with a new file in the same script run.
        import streamlit as st
        from modules.invoice_scan import review_service
        st.session_state["invoice_file_uploader"] = "sentinel-should-survive"
        review_service.reset_session_for_new_upload()
        assert st.session_state.get("invoice_file_uploader") == "sentinel-should-survive"

    def test_new_upload_never_mixes_with_previous_review(self):
        # Stabilization sprint P0 bug #2: a different invoice must never
        # show any trace of the previous one.
        from modules.invoice_scan import review_service
        old_meds = [{"name": f"Old{i}", "batch_number": f"OB{i}",
                     "expiry_date": "1/28", "quantity": "1", "mrp": "10",
                     "rate": "5", "gst_percent": "5"} for i in range(6)]
        review_service.initialise_review_session("hash_old", "old.jpg", old_meds)
        assert len(review_service.get_medicines()) == 6

        new_meds = [{"name": "New1", "batch_number": "NB1",
                     "expiry_date": "2/29", "quantity": "1", "mrp": "20",
                     "rate": "15", "gst_percent": "5"},
                    {"name": "New2", "batch_number": "NB2",
                     "expiry_date": "3/29", "quantity": "1", "mrp": "30",
                     "rate": "25", "gst_percent": "5"}]
        new_hash = "hash_new"
        if not review_service.is_review_session_active(new_hash):
            review_service.reset_session_for_new_upload()
        review_service.initialise_review_session(new_hash, "new.jpg", new_meds)

        final = review_service.get_medicines()
        assert len(final) == 2
        names = [m["name"] for m in final]
        assert all(n.startswith("New") for n in names)
        assert not any(n.startswith("Old") for n in names)

    def test_same_hash_reuploaded_reuses_cache_not_reset(self):
        # Stabilization sprint P0 bug #1: re-uploading the SAME invoice
        # (same SHA-256) must reuse the cached review, not reset it.
        from modules.invoice_scan import review_service
        meds = _sample_medicines(3)
        review_service.initialise_review_session("same_hash", "inv.jpg", meds)
        review_service.update_medicine(0, "name", "User-edited name")

        # Simulate the exact upload_ui.py guard for a re-upload of the
        # identical file (same hash) - must NOT reset.
        same_hash = "same_hash"
        if not review_service.is_review_session_active(same_hash):
            review_service.reset_session_for_new_upload()

        assert review_service.get_medicines()[0]["name"] == "User-edited name", (
            "Re-uploading the identical file must preserve the existing "
            "(possibly edited) review, not reset it."
        )


class TestPageIsolation:
    """Only modules/invoice_scan/* may read or write the review session
    key. Other pages (Dashboard, Sales, Products, Alerts) must never
    reference it, structurally guaranteeing review data cannot leak
    into another page's render."""

    def test_no_other_module_references_session_key(self):
        import os
        forbidden_dirs = [
            "modules/dashboard", "modules/sales",
            "modules/products", "modules/alerts",
        ]
        for d in forbidden_dirs:
            for root, _dirs, files in os.walk(d):
                for fname in files:
                    if not fname.endswith(".py"):
                        continue
                    path = os.path.join(root, fname)
                    content = open(path).read()
                    assert "invoice_review" not in content, (
                        f"{path} must never reference the invoice review "
                        f"session key - review state belongs only to "
                        f"Invoice Scan."
                    )

    def test_app_py_logout_clears_review_session(self):
        # Stabilization sprint P0 bug #3: logout must destroy the review
        # session, not just the auth session.
        src = open("app.py").read()
        assert "review_service.clear_session()" in src, (
            "app.py's logout handler must call review_service.clear_session()"
        )
        # Confirm it's actually wired into the Logout button handler,
        # not just imported/called somewhere unrelated.
        logout_idx = src.index('st.button("Logout"')
        nearby = src[logout_idx:logout_idx + 600]
        assert "review_service.clear_session()" in nearby
        assert "end_session()" in nearby

    def test_upload_ui_resets_only_after_validation_succeeds(self):
        # Stabilization sprint fix: an invalid/rejected upload attempt
        # must not destroy a valid existing review. The reset call must
        # appear AFTER process_invoice_upload() succeeds (i.e. after the
        # try/except ValidationError block), not before it.
        #
        # Test mis-specification fix: the original search used the bare
        # function name "reset_session_for_new_upload()", which also
        # matches an explanatory CODE COMMENT earlier in the file (line
        # ~80, "...would silently start reset_session_for_new_upload()
        # and discard...") that predates the real call site - causing a
        # false failure even though the actual call order was always
        # correct. Retargeted to the real call's exact syntax,
        # "review_service.reset_session_for_new_upload()", which the
        # module-prefixed comment near the real call does not
        # incidentally match (it reads "...reset_session_for_new_upload's
        # docstring", with no trailing parentheses) and which appears
        # exactly once in the file - the genuine call site.
        src = open("modules/invoice_scan/upload_ui.py").read()
        assert src.count("review_service.reset_session_for_new_upload()") == 1, (
            "Expected exactly one real call to "
            "review_service.reset_session_for_new_upload()"
        )
        validation_error_idx = src.index("except ValidationError as error:")
        reset_idx = src.index("review_service.reset_session_for_new_upload()")
        assert reset_idx > validation_error_idx, (
            "reset_session_for_new_upload() must be called only after the "
            "upload has passed validation, not before"
        )

    def test_app_py_navigation_does_not_clear_review_session(self):
        # Originally named
        # test_app_py_clears_review_session_when_navigating_away_from_invoice_scan
        # and asserted the v2.13.4 "isolation" guard (clear the review
        # session on every navigation away from Invoice Scan). That
        # guard was deliberately REMOVED in the "Final stabilization
        # fix" (v2.13.6, see app.py's own comment at the removal site):
        # the review must now survive page navigation and remain
        # available until "Clear Review" is clicked or a genuinely
        # different-hash invoice is uploaded - navigation alone must
        # never clear it. This test asserted the OLD, deliberately
        # reversed behavior and was stale since v2.13.6 shipped.
        # Rewritten to assert the CURRENT, intended behavior: no
        # navigation-based clear guard exists, and clear_session() is
        # called from exactly one place - the Logout handler.
        src = open("app.py").read()
        assert 'if selected_page != "🧾 Invoice Scan":' not in src, (
            "The v2.13.4 navigation-clears-review guard was deliberately "
            "removed in v2.13.6 and must not be reintroduced."
        )
        # Count only real (non-comment) call lines - app.py's own
        # explanatory comments legitimately mention this call by name
        # near the real site, same pitfall as the sibling test above.
        real_call_lines = [
            i for i, line in enumerate(src.split("\n"))
            if "review_service.clear_session()" in line
            and not line.strip().startswith("#")
        ]
        assert len(real_call_lines) == 1, (
            "review_service.clear_session() must be called from exactly "
            f"one real (non-comment) line - found {len(real_call_lines)}"
        )
        logout_idx = src.index('st.button("Logout"')
        clear_idx = src.index("review_service.clear_session()\n", logout_idx)
        assert clear_idx > logout_idx, (
            "The single clear_session() call must be inside the Logout "
            "handler."
        )
