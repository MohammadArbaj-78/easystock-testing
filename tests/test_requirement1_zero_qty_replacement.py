"""
Focused tests for Requirement 1: zero-quantity medicine replacement.

Same medicine name + an existing quantity == 0 record -> the new
invoice row reuses/replaces that record (batch/expiry/mrp/rate/gst all
overwritten with the new invoice's values), even when the incoming
batch and expiry differ from the old record's own. This is explicitly
NOT general merging: a non-zero-quantity record with a different batch
or expiry must still stay separate, exactly as before this change.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import initialize_database, get_connection
from modules.products import service as products_service
from modules.products import repository as products_repository


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


class TestRequirement1ZeroQuantityReplacement:
    def test_zero_qty_same_batch_expiry_replacement_works(self, tmp_path, monkeypatch):
        """Test 1: same medicine + existing quantity 0 + same batch/expiry."""
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        expiry = _future_expiry(6)
        product_id = products_service.add_product(store_id, {
            "name": "Medicine A", "batch_number": "OLD",
            "expiry_date": expiry, "quantity": 5.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        products_service.return_medicine(store_id, product_id)  # -> quantity 0

        outcome = products_service.save_or_merge_invoice_lot(store_id, {
            "name": "Medicine A", "batch_number": "OLD", "expiry_date": expiry,
            "quantity": "20", "mrp": "12", "rate": "9", "gst_percent": "5",
            "purchase_date": "",
        })
        assert outcome["status"] == "merged"
        assert outcome["product_id"] == product_id

        product = products_repository.get_product_by_id(store_id, product_id)
        assert product["quantity"] == 20
        assert product["batch_number"] == "OLD"
        assert product["expiry_date"] == expiry

        all_products = products_repository.get_all_products(store_id, search_term="Medicine A")
        assert len(all_products) == 1  # not an extra separate row

    def test_zero_qty_different_batch_expiry_replacement_still_works(self, tmp_path, monkeypatch):
        """Test 2: same medicine + existing quantity 0 + different batch/expiry."""
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        product_id = products_service.add_product(store_id, {
            "name": "Medicine A", "batch_number": "OLD",
            "expiry_date": _future_expiry(3), "quantity": 5.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        products_service.return_medicine(store_id, product_id)  # -> quantity 0

        new_expiry = _future_expiry(12)
        outcome = products_service.save_or_merge_invoice_lot(store_id, {
            "name": "Medicine A", "batch_number": "NEW", "expiry_date": new_expiry,
            "quantity": "20", "mrp": "15", "rate": "11", "gst_percent": "12",
            "purchase_date": "",
        })
        assert outcome["status"] == "merged"
        assert outcome["product_id"] == product_id  # same record REUSED, not a new one

        product = products_repository.get_product_by_id(store_id, product_id)
        assert product["quantity"] == 20
        assert product["batch_number"] == "NEW"
        assert product["expiry_date"] == new_expiry
        assert product["mrp"] == 15

        all_products = products_repository.get_all_products(store_id, search_term="Medicine A")
        assert len(all_products) == 1  # the old zero-qty record does NOT remain separate

    def test_nonzero_qty_different_batch_expiry_stays_separate_unchanged(self, tmp_path, monkeypatch):
        """Test 3: same medicine + existing quantity > 0 + different batch/expiry
        -> existing (pre-Requirement-1) behavior is unchanged: separate rows."""
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        old_id = products_service.add_product(store_id, {
            "name": "Medicine A", "batch_number": "OLD",
            "expiry_date": _future_expiry(3), "quantity": 10.0,  # NOT zero
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })

        outcome = products_service.save_or_merge_invoice_lot(store_id, {
            "name": "Medicine A", "batch_number": "NEW", "expiry_date": _future_expiry(12),
            "quantity": "20", "mrp": "15", "rate": "11", "gst_percent": "12",
            "purchase_date": "",
        })
        assert outcome["status"] == "created"  # a NEW separate row, not a replacement
        assert outcome["product_id"] != old_id

        old_product = products_repository.get_product_by_id(store_id, old_id)
        assert old_product["quantity"] == 10
        assert old_product["batch_number"] == "OLD"  # completely untouched

        all_products = products_repository.get_all_products(store_id, search_term="Medicine A")
        assert len(all_products) == 2  # both remain, separate

    def test_different_medicine_unaffected(self, tmp_path, monkeypatch):
        """Test 4: a zero-quantity record of a DIFFERENT medicine name
        must never be touched by an unrelated invoice row."""
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        zero_id = products_service.add_product(store_id, {
            "name": "Medicine Z", "batch_number": "Z1",
            "expiry_date": _future_expiry(3), "quantity": 5.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        products_service.return_medicine(store_id, zero_id)

        outcome = products_service.save_or_merge_invoice_lot(store_id, {
            "name": "Medicine A", "batch_number": "X", "expiry_date": _future_expiry(6),
            "quantity": "20", "mrp": "15", "rate": "11", "gst_percent": "12",
            "purchase_date": "",
        })
        assert outcome["status"] == "created"
        assert outcome["product_id"] != zero_id

        zero_product = products_repository.get_product_by_id(store_id, zero_id)
        assert zero_product["quantity"] == 0  # completely untouched
        assert zero_product["batch_number"] == "Z1"

    def test_exact_match_still_takes_priority_over_zero_qty_reuse(self, tmp_path, monkeypatch):
        """Same medicine, exact batch+expiry match on the zero-qty row
        itself still goes through the ordinary exact-match merge path
        (same visible result, existing code path unmodified)."""
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        expiry = _future_expiry(6)
        product_id = products_service.add_product(store_id, {
            "name": "Medicine A", "batch_number": "SAME",
            "expiry_date": expiry, "quantity": 5.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        products_service.return_medicine(store_id, product_id)

        outcome = products_service.save_or_merge_invoice_lot(store_id, {
            "name": "Medicine A", "batch_number": "SAME", "expiry_date": expiry,
            "quantity": "20", "mrp": "10", "rate": "8", "gst_percent": "5",
            "purchase_date": "",
        })
        assert outcome["status"] == "merged"
        assert outcome["product_id"] == product_id
        product = products_repository.get_product_by_id(store_id, product_id)
        assert product["quantity"] == 20
