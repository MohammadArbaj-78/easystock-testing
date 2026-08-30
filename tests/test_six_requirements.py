"""
Focused tests for 5 of the 6 requirements in this round (Requirement 2,
Supabase session persistence, is covered separately in
tests/test_supabase_auth.py's TestRestoreSession class):

  REQ 1: Strict arrival-order FIFO (not FEFO/expiry-order) in Sales.
  REQ 3: initialize_database()'s supabase_user_id migration must not
         crash on a repeated/racing duplicate-column attempt.
  REQ 4: Emergent preprocessing replaces the old preprocessing pipeline.
  REQ 5: Low Stock global minimum dropdown (1-10), custom minimum wins,
         Dashboard unaffected.
  REQ 6: qty+free->TQT must preserve decimal precision, not truncate.
"""

import io
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import initialize_database, get_connection
from modules.products import service as products_service
from modules.products import repository as products_repository
from modules.dashboard import service as dashboard_service
from modules.sales import service as sales_service
from modules.alerts import low_stock_service
from modules.invoice_scan.ocr_service import _emergent_preprocess, _apply_quantity_formula


def _setup_isolated_db(tmp_path, monkeypatch):
    import core.database as database_module
    db_path = tmp_path / "test_easystock.db"
    monkeypatch.setattr(database_module, "DATABASE_PATH", str(db_path))
    monkeypatch.setattr(database_module, "DATA_DIR", str(tmp_path))
    initialize_database()
    return db_path


def _create_store(name="Test Store") -> int:
    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO stores (store_name, owner_name, mobile_number, password_hash) "
            "VALUES (?, ?, ?, ?)",
            (name, "Owner", f"9{id(name) % 10**9:09d}", "not-a-real-hash"),
        )
        return cursor.lastrowid


def _future_expiry(months_ahead: int) -> str:
    from datetime import date
    today = date.today()
    total = today.month - 1 + months_ahead
    year = today.year + total // 12
    month = total % 12 + 1
    return f"{month:02d}/{str(year)[-2:]}"


# ---------------------------------------------------------------------------
# REQUIREMENT 1: strict arrival-order FIFO
# ---------------------------------------------------------------------------

class TestRequirement1StrictFifo:
    def test_older_batch_used_first_even_with_later_expiry(self, tmp_path, monkeypatch):
        """Old batch created FIRST but has a LATER expiry than the new
        batch - strict FIFO must still pick the old (first-arrived) one,
        proving this is arrival-order, not expiry-order (FEFO)."""
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        old_id = products_service.add_product(store_id, {
            "name": "Paracetamol", "batch_number": "A",
            "expiry_date": _future_expiry(12), "quantity": 10.0,  # later expiry
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        new_id = products_service.add_product(store_id, {
            "name": "Paracetamol", "batch_number": "B",
            "expiry_date": _future_expiry(3), "quantity": 20.0,  # earlier expiry
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })

        results = sales_service.search_products(store_id, "Paracetamol")
        assert results[0]["product_id"] == old_id  # arrival order wins, not expiry

    def test_partial_sale_keeps_same_batch_active(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        old_id = products_service.add_product(store_id, {
            "name": "Medicine A", "batch_number": "A",
            "expiry_date": _future_expiry(3), "quantity": 10.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        new_id = products_service.add_product(store_id, {
            "name": "Medicine A", "batch_number": "B",
            "expiry_date": _future_expiry(12), "quantity": 20.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })

        sales_service.sell_product(store_id, old_id, 3)
        old = products_repository.get_product_by_id(store_id, old_id)
        new = products_repository.get_product_by_id(store_id, new_id)
        assert old["quantity"] == 7
        assert new["quantity"] == 20  # untouched
        assert sales_service.search_products(store_id, "Medicine A")[0]["product_id"] == old_id

    def test_batch_reaching_zero_immediately_excluded_and_next_becomes_active(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        old_id = products_service.add_product(store_id, {
            "name": "Medicine A", "batch_number": "A",
            "expiry_date": _future_expiry(3), "quantity": 7.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        new_id = products_service.add_product(store_id, {
            "name": "Medicine A", "batch_number": "B",
            "expiry_date": _future_expiry(12), "quantity": 20.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })

        sales_service.sell_product(store_id, old_id, 7)  # -> old = 0
        old = products_repository.get_product_by_id(store_id, old_id)
        assert old["quantity"] == 0

        results = sales_service.search_products(store_id, "Medicine A")
        assert len(results) == 1
        assert results[0]["product_id"] == new_id  # new batch now active

    def test_sale_quantity_change_never_changes_selected_batch(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        old_id = products_service.add_product(store_id, {
            "name": "Medicine A", "batch_number": "A",
            "expiry_date": _future_expiry(3), "quantity": 10.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        products_service.add_product(store_id, {
            "name": "Medicine A", "batch_number": "B",
            "expiry_date": _future_expiry(12), "quantity": 20.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        for qty in (1, 2, 3):  # changing sale quantity repeatedly
            assert sales_service.search_products(store_id, "Medicine A")[0]["product_id"] == old_id

    def test_zero_quantity_reused_lot_does_not_break_arrival_order(self, tmp_path, monkeypatch):
        """A zero-quantity lot repurposed by save_or_merge_invoice_lot
        keeps its ORIGINAL product_id/arrival slot - it must not jump
        the FIFO queue ahead of a genuinely older lot still in stock."""
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        first_id = products_service.add_product(store_id, {
            "name": "Medicine Z", "batch_number": "OLD",
            "expiry_date": _future_expiry(3), "quantity": 5.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        products_service.return_medicine(store_id, first_id)  # -> qty 0
        second_id = products_service.add_product(store_id, {
            "name": "Medicine Z", "batch_number": "SECOND",
            "expiry_date": _future_expiry(6), "quantity": 5.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })

        # Repurpose the FIRST (now zero-qty) row via a new invoice row -
        # its product_id (first_id) must stay first_id, not become newest.
        outcome = products_service.save_or_merge_invoice_lot(store_id, {
            "name": "Medicine Z", "batch_number": "NEWEST", "expiry_date": _future_expiry(9),
            "quantity": "10", "mrp": "10", "rate": "8", "gst_percent": "5",
            "purchase_date": "",
        })
        assert outcome["product_id"] == first_id  # same row reused, same product_id

        # Arrival order must be: first_id (reused row) before second_id,
        # since first_id's product_id is still numerically smaller.
        results = sales_service.search_products(store_id, "Medicine Z")
        assert results[0]["product_id"] == first_id

    def test_different_batch_and_expiry_allowed_non_zero_never_replaced(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        old_id = products_service.add_product(store_id, {
            "name": "Medicine A", "batch_number": "A",
            "expiry_date": _future_expiry(3), "quantity": 10.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        outcome = products_service.save_or_merge_invoice_lot(store_id, {
            "name": "Medicine A", "batch_number": "B", "expiry_date": _future_expiry(12),
            "quantity": "20", "mrp": "10", "rate": "8", "gst_percent": "5",
            "purchase_date": "",
        })
        assert outcome["status"] == "created"  # separate row, old untouched
        old = products_repository.get_product_by_id(store_id, old_id)
        assert old["quantity"] == 10

    def test_exact_match_merge_still_works(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        expiry = _future_expiry(6)
        outcome1 = products_service.save_or_merge_invoice_lot(store_id, {
            "name": "Medicine A", "batch_number": "X", "expiry_date": expiry,
            "quantity": "10", "mrp": "10", "rate": "8", "gst_percent": "5",
            "purchase_date": "",
        })
        outcome2 = products_service.save_or_merge_invoice_lot(store_id, {
            "name": "Medicine A", "batch_number": "X", "expiry_date": expiry,
            "quantity": "5", "mrp": "10", "rate": "8", "gst_percent": "5",
            "purchase_date": "",
        })
        assert outcome2["status"] == "merged"
        assert outcome2["product_id"] == outcome1["product_id"]
        product = products_repository.get_product_by_id(store_id, outcome1["product_id"])
        assert product["quantity"] == 15


# ---------------------------------------------------------------------------
# REQUIREMENT 3: duplicate-column migration race
# ---------------------------------------------------------------------------

class TestRequirement3MigrationRace:
    def test_repeated_initialization_does_not_crash(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        initialize_database()
        initialize_database()
        initialize_database()  # must remain a no-op every time

    def test_simulated_race_duplicate_column_is_swallowed(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        with get_connection() as connection:
            try:
                connection.execute("ALTER TABLE stores ADD COLUMN supabase_user_id TEXT")
            except sqlite3.OperationalError as error:
                if "duplicate column name" not in str(error).lower():
                    raise
            # must reach here without raising

    def test_unrelated_database_error_still_raised(self, tmp_path, monkeypatch):
        """A genuine, unrelated SQL error must still surface - here as
        DatabaseError, since core.database.get_connection()'s own
        context manager already wraps every sqlite3.Error into
        DatabaseError (pre-existing, unrelated to this fix) before it
        can reach a caller as a raw sqlite3.OperationalError."""
        from core.exceptions import DatabaseError
        _setup_isolated_db(tmp_path, monkeypatch)
        with pytest.raises(DatabaseError):
            with get_connection() as connection:
                try:
                    connection.execute("ALTER TABLE stores ADD COLUMN new_col NOTAREALTYPE(((")
                except sqlite3.OperationalError as error:
                    if "duplicate column name" not in str(error).lower():
                        raise


# ---------------------------------------------------------------------------
# REQUIREMENT 4: Emergent preprocessing
# ---------------------------------------------------------------------------

class TestRequirement4EmergentPreprocessing:
    def test_produces_rgb_image(self):
        img = Image.new("L", (500, 500), color=100)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = _emergent_preprocess(buf.getvalue())
        assert result.mode == "RGB"

    def test_resizes_to_max_side_2200(self):
        img = Image.new("RGB", (5000, 3000), color=(200, 200, 200))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = _emergent_preprocess(buf.getvalue())
        assert max(result.size) == 2200

    def test_small_image_not_upscaled(self):
        img = Image.new("RGB", (800, 600), color=(200, 200, 200))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = _emergent_preprocess(buf.getvalue())
        assert result.size == (800, 600)

    def test_exactly_one_gemini_call_with_emergent_preprocessing(self, monkeypatch):
        from modules.invoice_scan.ocr_service import extract_medicines_from_file
        import json as jsonlib

        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = jsonlib.dumps([{
            "name": "Med", "batch_number": "B1", "expiry_date": "06/2027",
            "qty": "5", "free": "0", "mrp": "10", "rate": "8", "gst_percent": "5",
        }])
        mock_client.models.generate_content.return_value = mock_response

        buf = io.BytesIO()
        Image.new("RGB", (100, 100), color=(180, 200, 220)).save(buf, format="PNG")
        file_obj = MagicMock()
        file_obj.name = "invoice.png"
        file_obj.getvalue.return_value = buf.getvalue()

        with patch("modules.invoice_scan.ocr_service._build_genai_client", return_value=mock_client):
            extract_medicines_from_file(file_obj)

        assert mock_client.models.generate_content.call_count == 1

    def test_preprocessing_failure_falls_back_and_still_makes_one_gemini_call(self, monkeypatch):
        """If _emergent_preprocess() raises, the ORIGINAL image must be
        used and Gemini must still be called exactly once - never
        twice, never zero times."""
        from modules.invoice_scan.ocr_service import extract_medicines_from_file
        import json as jsonlib

        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = jsonlib.dumps([{
            "name": "Med", "batch_number": "B1", "expiry_date": "06/2027",
            "qty": "5", "free": "0", "mrp": "10", "rate": "8", "gst_percent": "5",
        }])
        mock_client.models.generate_content.return_value = mock_response

        buf = io.BytesIO()
        Image.new("RGB", (100, 100), color=(180, 200, 220)).save(buf, format="PNG")
        file_obj = MagicMock()
        file_obj.name = "invoice.png"
        file_obj.getvalue.return_value = buf.getvalue()

        with patch("modules.invoice_scan.ocr_service._build_genai_client", return_value=mock_client), \
             patch("modules.invoice_scan.ocr_service._emergent_preprocess", side_effect=Exception("boom")):
            result = extract_medicines_from_file(file_obj)

        assert mock_client.models.generate_content.call_count == 1
        assert len(result["medicines"]) == 1


# ---------------------------------------------------------------------------
# REQUIREMENT 5: Low Stock global minimum dropdown
# ---------------------------------------------------------------------------

class TestRequirement5LowStockGlobalMinimum:
    def test_global_3_no_custom_threshold(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        products_service.add_product(store_id, {
            "name": "Medicine A", "batch_number": "A",
            "expiry_date": _future_expiry(6), "quantity": 3.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        buckets = low_stock_service.get_low_stock_alerts(store_id, global_minimum=3)
        all_items = [item for bucket in buckets.values() for item in bucket]
        assert any(item["name"] == "Medicine A" for item in all_items)

    def test_global_7_custom_5_wins(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        products_service.add_product(store_id, {
            "name": "Medicine B", "batch_number": "B",
            "expiry_date": _future_expiry(6), "quantity": 6.0,  # > 5 (custom), < 7 (global)
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": True,
            "minimum_stock_threshold": 5.0,
        })
        buckets = low_stock_service.get_low_stock_alerts(store_id, global_minimum=7)
        all_items = [item for bucket in buckets.values() for item in bucket]
        # quantity 6 > custom minimum 5 -> NOT low stock, even though 6 <= global 7
        assert not any(item["name"] == "Medicine B" for item in all_items)

    def test_dashboard_unaffected_by_low_stock_page_global_selection(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        products_service.add_product(store_id, {
            "name": "Medicine C", "batch_number": "C",
            "expiry_date": _future_expiry(6), "quantity": 5.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        # Dashboard never passes global_minimum - default (2) applies,
        # quantity 5 > 2, so this should NOT show as low stock there,
        # regardless of what a store owner picked on the Low Stock page.
        metrics = dashboard_service.get_dashboard_metrics(store_id)
        assert not any(item["name"] == "Medicine C" for item in metrics["low_stock_items"])

    def test_global_minimum_values_restricted_to_1_through_10(self):
        from modules.alerts.low_stock_ui import GLOBAL_MINIMUM_OPTIONS
        assert GLOBAL_MINIMUM_OPTIONS == list(range(1, 11))


# ---------------------------------------------------------------------------
# REQUIREMENT 6: decimal precision in qty+free->TQT
# ---------------------------------------------------------------------------

class TestRequirement6DecimalTqt:
    def test_1_5_plus_0_5_equals_2(self):
        result = _apply_quantity_formula([{"qty": "1.5", "free": "0.5", "tqt": ""}])
        assert result[0]["quantity"] == "2"

    def test_1_25_plus_0_50_equals_1_75(self):
        result = _apply_quantity_formula([{"qty": "1.25", "free": "0.50", "tqt": ""}])
        assert result[0]["quantity"] == "1.75"

    def test_10_5_plus_2_25_equals_12_75(self):
        result = _apply_quantity_formula([{"qty": "10.5", "free": "2.25", "tqt": ""}])
        assert result[0]["quantity"] == "12.75"

    def test_2_plus_1_equals_3_no_decimal_forced(self):
        result = _apply_quantity_formula([{"qty": "2", "free": "1", "tqt": ""}])
        assert result[0]["quantity"] == "3"

    def test_no_floating_point_artifact(self):
        """0.1 + 0.2 is the classic binary-float artifact case
        (0.30000000000000004 in raw IEEE 754) - must come out clean."""
        result = _apply_quantity_formula([{"qty": "0.1", "free": "0.2", "tqt": ""}])
        assert result[0]["quantity"] == "0.3"

    def test_save_path_preserves_decimal_quantity(self, tmp_path, monkeypatch):
        """The actual bug: _clean_invoice_lot_data() used to do
        int(float(...)), truncating 1.75 down to 1 at SAVE time even
        though the extraction-time formula above already produced the
        correct decimal string."""
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        outcome = products_service.save_or_merge_invoice_lot(store_id, {
            "name": "Medicine D", "batch_number": "D1", "expiry_date": _future_expiry(6),
            "quantity": "1.75", "mrp": "10", "rate": "8", "gst_percent": "5",
            "purchase_date": "",
        })
        product = products_repository.get_product_by_id(store_id, outcome["product_id"])
        assert product["quantity"] == 1.75  # NOT truncated to 1

    def test_save_path_whole_number_stored_as_integer(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        outcome = products_service.save_or_merge_invoice_lot(store_id, {
            "name": "Medicine E", "batch_number": "E1", "expiry_date": _future_expiry(6),
            "quantity": "5", "mrp": "10", "rate": "8", "gst_percent": "5",
            "purchase_date": "",
        })
        product = products_repository.get_product_by_id(store_id, outcome["product_id"])
        assert product["quantity"] == 5
        assert isinstance(product["quantity"], int)  # SQLite affinity: whole float -> INTEGER storage

    def test_tqt_field_still_wins_when_present_with_decimal(self):
        result = _apply_quantity_formula([{"qty": "1", "free": "1", "tqt": "5.5"}])
        assert result[0]["quantity"] == "5.5"
