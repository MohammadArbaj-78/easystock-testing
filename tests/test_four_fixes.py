"""
Focused tests for four surgical bug fixes:

  FIX 1: Dashboard's Expiry Alert (metric cards + detail expanders) must
         exclude a returned (quantity == 0) medicine immediately, the
         same quantity-0 exclusion the separate Expiry Alerts page
         already applies. Low Stock is unaffected.
  FIX 2: Invoice Save merges duplicate rows ONLY when name + batch +
         expiry all match (same stock lot). Different batch or expiry
         stays separate. Preview/Review never merges before Save.
  FIX 3: Sales search shows only one (FIFO-first / earliest-expiry)
         in-stock lot per medicine name; a newer batch is hidden while
         an older batch of the same medicine still has stock > 0.
  FIX 4: A Product Management "Add Product" validation failure leaves
         every already-typed field widget's session_state value intact
         (no clear_on_submit wipe); a successful add still resets the
         form, via the same two-phase sentinel already used for the
         custom-threshold checkbox.

Uses a real, isolated SQLite database per test (bypassing core.auth,
which needs bcrypt - unavailable in this offline sandbox - by inserting
a store row directly, matching the exact schema in core/database.py).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from core.database import initialize_database, get_connection
from modules.products import service as products_service
from modules.products import repository as products_repository
from modules.dashboard import service as dashboard_service
from modules.sales import service as sales_service
from core.exceptions import ValidationError


def _setup_isolated_db(tmp_path, monkeypatch):
    """Fresh, isolated SQLite database per test - same pattern already
    used by tests/test_expiry_alerts.py and
    tests/test_products_ui_threshold_checkbox.py. A plain helper
    (rather than a pytest fixture) since this project's offline test
    harness only supports the built-in tmp_path/monkeypatch fixtures,
    not arbitrary custom ones - see tests/README or run_tests.py."""
    import core.database as database_module

    db_path = tmp_path / "test_easystock.db"
    monkeypatch.setattr(database_module, "DATABASE_PATH", str(db_path))
    monkeypatch.setattr(database_module, "DATA_DIR", str(tmp_path))
    initialize_database()
    return db_path


def _create_store(name="Test Store") -> int:
    """Insert a store row directly, bypassing core.auth.signup (which
    needs bcrypt - not installed in this offline sandbox). Matches the
    exact stores table schema in core/database.py."""
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


@pytest.fixture(autouse=True)
def clean_session_state():
    """Clear session state before/after each test - same pattern as
    tests/test_review_service.py's own autouse fixture."""
    st.session_state.clear()
    yield
    st.session_state.clear()


# ---------------------------------------------------------------------------
# FIX 1: Dashboard Expiry Alert after Return
# ---------------------------------------------------------------------------

class TestFix1DashboardExpiryAlertAfterReturn:
    def test_returned_medicine_excluded_from_expiring_soon(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        product_id = products_service.add_product(store_id, {
            "name": "DEMISONE TAB", "batch_number": "JKEH25101",
            "expiry_date": _future_expiry(0), "quantity": 5.0,
            "mrp": 20.0, "rate": 18.0, "gst_percent": 12.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })

        before = dashboard_service.get_dashboard_metrics(store_id)
        assert any(i["product_id"] == product_id for i in before["expiring_soon_items"])

        products_service.return_medicine(store_id, product_id)

        after = dashboard_service.get_dashboard_metrics(store_id)
        assert all(i["product_id"] != product_id for i in after["expiring_soon_items"])
        assert all(i["product_id"] != product_id for i in after["expired_items"])

    def test_returned_medicine_excluded_from_expired(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        product_id = products_service.add_product(store_id, {
            "name": "OLDMED TAB", "batch_number": "B1",
            "expiry_date": _future_expiry(0), "quantity": 5.0,
            "mrp": 20.0, "rate": 18.0, "gst_percent": 12.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        # Force it into the past so it counts as expired (add_product
        # itself blocks past expiry dates by design - edit around it).
        with get_connection() as connection:
            connection.execute(
                "UPDATE products SET expiry_date = ? WHERE product_id = ?",
                ("01/20", product_id),
            )

        before = dashboard_service.get_dashboard_metrics(store_id)
        assert any(i["product_id"] == product_id for i in before["expired_items"])

        products_service.return_medicine(store_id, product_id)

        after = dashboard_service.get_dashboard_metrics(store_id)
        assert all(i["product_id"] != product_id for i in after["expired_items"])

    def test_low_stock_unaffected_by_return(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        """Low Stock must still list a returned (quantity 0) product -
        FIX 1 must not touch Low Stock behavior at all."""
        store_id = _create_store()
        product_id = products_service.add_product(store_id, {
            "name": "LOWSTOCK MED", "batch_number": "B2",
            "expiry_date": _future_expiry(6), "quantity": 5.0,
            "mrp": 20.0, "rate": 18.0, "gst_percent": 12.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        products_service.return_medicine(store_id, product_id)

        metrics = dashboard_service.get_dashboard_metrics(store_id)
        assert any(i["product_id"] == product_id for i in metrics["low_stock_items"])


# ---------------------------------------------------------------------------
# FIX 2: Invoice duplicate-row merge ONLY at Save, ONLY same batch+expiry
# ---------------------------------------------------------------------------

class TestFix2DuplicateInvoiceRowMergeOnSave:
    def test_same_batch_same_expiry_merges_with_combined_quantity(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        from modules.products.service import save_or_merge_invoice_lot

        lot = {
            "name": "Medicine A", "batch_number": "X", "expiry_date": _future_expiry(12),
            "quantity": "10", "mrp": "50", "rate": "40", "gst_percent": "12",
            "purchase_date": "",
        }
        outcome1 = save_or_merge_invoice_lot(store_id, dict(lot))
        assert outcome1["status"] == "created"

        lot2 = dict(lot)
        lot2["quantity"] = "5"
        outcome2 = save_or_merge_invoice_lot(store_id, lot2)
        assert outcome2["status"] == "merged"
        assert outcome2["product_id"] == outcome1["product_id"]

        product = products_repository.get_product_by_id(store_id, outcome1["product_id"])
        assert product["quantity"] == 15

        # Exactly one DB row for this lot - not two.
        all_products = products_repository.get_all_products(store_id, search_term="Medicine A")
        assert len(all_products) == 1

    def test_different_batch_stays_separate(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        from modules.products.service import save_or_merge_invoice_lot

        expiry = _future_expiry(12)
        outcome1 = save_or_merge_invoice_lot(store_id, {
            "name": "Medicine A", "batch_number": "X", "expiry_date": expiry,
            "quantity": "10", "mrp": "50", "rate": "40", "gst_percent": "12",
            "purchase_date": "",
        })
        outcome2 = save_or_merge_invoice_lot(store_id, {
            "name": "Medicine A", "batch_number": "Y", "expiry_date": expiry,
            "quantity": "5", "mrp": "50", "rate": "40", "gst_percent": "12",
            "purchase_date": "",
        })
        assert outcome1["status"] == "created"
        assert outcome2["status"] == "created"
        assert outcome1["product_id"] != outcome2["product_id"]

        all_products = products_repository.get_all_products(store_id, search_term="Medicine A")
        assert len(all_products) == 2
        quantities = sorted(p["quantity"] for p in all_products)
        assert quantities == [5, 10]

    def test_different_expiry_stays_separate(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        from modules.products.service import save_or_merge_invoice_lot

        outcome1 = save_or_merge_invoice_lot(store_id, {
            "name": "Medicine A", "batch_number": "X", "expiry_date": _future_expiry(6),
            "quantity": "10", "mrp": "50", "rate": "40", "gst_percent": "12",
            "purchase_date": "",
        })
        outcome2 = save_or_merge_invoice_lot(store_id, {
            "name": "Medicine A", "batch_number": "X", "expiry_date": _future_expiry(12),
            "quantity": "5", "mrp": "50", "rate": "40", "gst_percent": "12",
            "purchase_date": "",
        })
        assert outcome1["status"] == "created"
        assert outcome2["status"] == "created"
        assert outcome1["product_id"] != outcome2["product_id"]

    def test_preview_still_shows_separate_rows_before_save(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        """The Review session's in-memory medicine list must never be
        merged - only save_invoice_medicines (on Save) touches the DB."""
        from modules.invoice_scan import review_service

        ocr_result = {
            "medicines": [
                {"name": "Medicine A", "batch_number": "X", "expiry_date": _future_expiry(12),
                 "qty": "10", "free": "0", "tqt": "", "quantity": "10",
                 "mrp": "50", "rate": "40", "gst_percent": "12"},
                {"name": "Medicine A", "batch_number": "X", "expiry_date": _future_expiry(12),
                 "qty": "5", "free": "0", "tqt": "", "quantity": "5",
                 "mrp": "50", "rate": "40", "gst_percent": "12"},
            ],
            "medicine_count": 2, "extraction_time_seconds": 1.0, "model": "test",
        }
        review_service.initialise_review_session("hash123", "invoice.png", ocr_result["medicines"])

        medicines = review_service.get_medicines()
        assert len(medicines) == 2  # still two separate rows, not merged

    def test_save_merges_duplicate_rows_from_one_invoice(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        """End-to-end: two duplicate rows (same name+batch+expiry) in
        one review session merge into a single DB row on Save, with
        combined quantity."""
        from modules.invoice_scan import review_service

        store_id = _create_store()
        expiry = _future_expiry(12)
        ocr_result = {
            "medicines": [
                {"name": "Medicine A", "batch_number": "X", "expiry_date": expiry,
                 "qty": "10", "free": "0", "tqt": "", "quantity": "10",
                 "mrp": "50", "rate": "40", "gst_percent": "12"},
                {"name": "Medicine A", "batch_number": "X", "expiry_date": expiry,
                 "qty": "5", "free": "0", "tqt": "", "quantity": "5",
                 "mrp": "50", "rate": "40", "gst_percent": "12"},
            ],
            "medicine_count": 2, "extraction_time_seconds": 1.0, "model": "test",
        }
        review_service.initialise_review_session("hash456", "invoice.png", ocr_result["medicines"])

        result = review_service.save_invoice_medicines(store_id)
        assert result["saved"] == 2  # both rows processed successfully
        assert result["skipped"] == []

        all_products = products_repository.get_all_products(store_id, search_term="Medicine A")
        assert len(all_products) == 1  # merged into one DB row
        assert all_products[0]["quantity"] == 15


# ---------------------------------------------------------------------------
# FIX 3: Sales search FIFO - one batch per medicine, oldest first
# ---------------------------------------------------------------------------

class TestFix3SalesSearchFIFO:
    def _add_two_batches(self, store_id):
        old_id = products_service.add_product(store_id, {
            "name": "Medicine A", "batch_number": "OLD",
            "expiry_date": _future_expiry(3), "quantity": 10.0,
            "mrp": 50.0, "rate": 40.0, "gst_percent": 12.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        new_id = products_service.add_product(store_id, {
            "name": "Medicine A", "batch_number": "NEW",
            "expiry_date": _future_expiry(12), "quantity": 30.0,
            "mrp": 50.0, "rate": 40.0, "gst_percent": 12.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        return old_id, new_id

    def test_only_older_batch_shown_while_it_has_stock(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        old_id, new_id = self._add_two_batches(store_id)

        results = sales_service.search_products(store_id, "Medicine A")
        assert len(results) == 1
        assert results[0]["product_id"] == old_id
        assert results[0]["batch_number"] == "OLD"

    def test_newer_batch_appears_after_older_reaches_zero(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        old_id, new_id = self._add_two_batches(store_id)

        # Sell out the older batch entirely via the real FIFO sell path.
        sales_service.sell_product(store_id, old_id, 10)

        results = sales_service.search_products(store_id, "Medicine A")
        assert len(results) == 1
        assert results[0]["product_id"] == new_id
        assert results[0]["batch_number"] == "NEW"

    def test_three_batches_follow_fifo_order_as_each_empties(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        b1 = products_service.add_product(store_id, {
            "name": "Medicine B", "batch_number": "B1",
            "expiry_date": _future_expiry(2), "quantity": 5.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        b2 = products_service.add_product(store_id, {
            "name": "Medicine B", "batch_number": "B2",
            "expiry_date": _future_expiry(6), "quantity": 5.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        b3 = products_service.add_product(store_id, {
            "name": "Medicine B", "batch_number": "B3",
            "expiry_date": _future_expiry(10), "quantity": 5.0,
            "mrp": 10.0, "rate": 8.0, "gst_percent": 5.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })

        assert sales_service.search_products(store_id, "Medicine B")[0]["product_id"] == b1
        sales_service.sell_product(store_id, b1, 5)
        assert sales_service.search_products(store_id, "Medicine B")[0]["product_id"] == b2
        sales_service.sell_product(store_id, b2, 5)
        assert sales_service.search_products(store_id, "Medicine B")[0]["product_id"] == b3

    def test_never_more_than_one_result_per_medicine_name(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        store_id = _create_store()
        self._add_two_batches(store_id)
        results = sales_service.search_products(store_id, "Medicine A")
        names = [r["name"].strip().lower() for r in results]
        assert len(names) == len(set(names))

    def test_sell_product_fifo_consumption_unchanged(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        """Fix 3 only changes search results, never which lot an actual
        sale consumes - sell_product's existing FIFO order (already
        correct) must be untouched."""
        store_id = _create_store()
        old_id, new_id = self._add_two_batches(store_id)

        # Selling via the NEW batch's product_id must still consume the
        # OLDER lot first (sell_product resolves by medicine name, not
        # literally the product_id clicked - unchanged existing rule).
        sales_service.sell_product(store_id, new_id, 4)

        old_product = products_repository.get_product_by_id(store_id, old_id)
        new_product = products_repository.get_product_by_id(store_id, new_id)
        assert old_product["quantity"] == 6   # reduced first
        assert new_product["quantity"] == 30  # untouched


# ---------------------------------------------------------------------------
# FIX 4: Product Management form preserves data on validation failure
# ---------------------------------------------------------------------------

class TestFix4ProductFormPreservesDataOnValidationFailure:
    def test_clear_helper_is_noop_without_success_sentinel(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        """Simulates a validation failure: the reset sentinel is never
        set, so the widget-clearing helper must leave every field's
        session_state value untouched."""
        from modules.products.ui import _clear_add_product_form_fields

        st.session_state["add_name"] = "Paracetamol"
        st.session_state["add_batch_number"] = "ABC123"
        st.session_state["add_mrp"] = 50.0

        _clear_add_product_form_fields("add")

        assert st.session_state["add_name"] == "Paracetamol"
        assert st.session_state["add_batch_number"] == "ABC123"
        assert st.session_state["add_mrp"] == 50.0

    def test_clear_helper_clears_fields_when_success_sentinel_set(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        """Simulates the successful-save path: the sentinel is set, so
        the helper must clear every Add Product field widget key -
        successful Save behavior (form resets) stays unchanged."""
        from modules.products.ui import _clear_add_product_form_fields

        st.session_state["add_name"] = "Paracetamol"
        st.session_state["add_batch_number"] = "ABC123"
        st.session_state["add_mrp"] = 50.0
        st.session_state["_reset_add_product_form"] = True

        _clear_add_product_form_fields("add")

        assert "add_name" not in st.session_state
        assert "add_batch_number" not in st.session_state
        assert "add_mrp" not in st.session_state
        assert "_reset_add_product_form" not in st.session_state  # sentinel consumed

    def test_incomplete_medicine_is_not_saved(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        """add_product itself must still reject an incomplete row -
        FIX 4 only preserves form state, never changes validation
        rules or lets an incomplete medicine through."""
        store_id = _create_store()
        with pytest.raises(ValidationError):
            products_service.add_product(store_id, {
                "name": "Paracetamol", "batch_number": "ABC123",
                "expiry_date": "",  # missing required field
                "quantity": 10.0, "mrp": 50.0, "rate": 40.0, "gst_percent": 12.0,
                "purchase_date": None, "_minimum_stock_threshold_enabled": False,
            })
        all_products = products_repository.get_all_products(store_id, search_term="Paracetamol")
        assert all_products == []

    def test_successful_add_still_works_unchanged(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        """Successful Save behavior (the product actually gets created)
        must be completely unchanged by FIX 4."""
        store_id = _create_store()
        product_id = products_service.add_product(store_id, {
            "name": "Paracetamol", "batch_number": "ABC123",
            "expiry_date": _future_expiry(6), "quantity": 10.0,
            "mrp": 50.0, "rate": 40.0, "gst_percent": 12.0,
            "purchase_date": None, "_minimum_stock_threshold_enabled": False,
        })
        product = products_repository.get_product_by_id(store_id, product_id)
        assert product["name"] == "Paracetamol"
        assert product["quantity"] == 10

    def test_add_product_form_no_longer_uses_clear_on_submit(self):
        """Direct code-level guard: the st.form(...) call line in
        _render_add_product_form must not pass clear_on_submit=True -
        that was the actual root cause this fix removes. Checked
        against just the st.form(...) call line itself, not the whole
        function source, since the function's own docstring explains
        the fix using that exact phrase in prose."""
        import inspect
        from modules.products import ui as products_ui
        source = inspect.getsource(products_ui._render_add_product_form)
        form_call_line = next(
            line for line in source.splitlines()
            if line.strip().startswith("with st.form(")
        )
        assert "clear_on_submit=True" not in form_call_line
        assert form_call_line.strip() == 'with st.form("add_product_form"):'
