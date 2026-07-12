"""
Tests for Module 7 (Low Stock Alerts): severity bucketing, search,
multi-tenant isolation, and real UI behavior via Streamlit AppTest.
"""

from datetime import date, timedelta

import pytest
from streamlit.testing.v1 import AppTest

from core.database import initialize_database
from core.auth import signup
from modules.products import service as products_service
from modules.alerts import low_stock_service


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    import core.database as database_module
    db_path = tmp_path / "test_easystock.db"
    monkeypatch.setattr(database_module, "DATABASE_PATH", str(db_path))
    monkeypatch.setattr(database_module, "DATA_DIR", str(tmp_path))
    initialize_database()
    return db_path


def _add(store_id, name, batch, qty, threshold=None):
    return products_service.add_product(store_id, {
        "name": name, "batch_number": batch,
        "expiry_date": date.today() + timedelta(days=200),
        "quantity": qty, "mrp": 10.0,
        "_minimum_stock_threshold_enabled": threshold is not None,
        "minimum_stock_threshold": threshold,
    })


class TestSeverityBucketing:
    def test_zero_quantity_is_critical(self, isolated_db):
        store_id = signup("Store", "O", "9876500401", "pass123")
        _add(store_id, "Zero Med", "Z01", 0)
        buckets = low_stock_service.get_low_stock_alerts(store_id)
        assert any(p["name"] == "Zero Med" for p in buckets["critical"])

    def test_below_half_threshold_is_warning(self, isolated_db):
        store_id = signup("Store", "O", "9876500402", "pass123")
        _add(store_id, "Low Med", "L01", 3)  # 3/10 = 30% -> WARNING
        buckets = low_stock_service.get_low_stock_alerts(store_id)
        assert any(p["name"] == "Low Med" for p in buckets["warning"])

    def test_above_half_threshold_but_still_low_is_low(self, isolated_db):
        store_id = signup("Store", "O", "9876500403", "pass123")
        _add(store_id, "Borderline Med", "B01", 8)  # 8/10 = 80% -> LOW
        buckets = low_stock_service.get_low_stock_alerts(store_id)
        assert any(p["name"] == "Borderline Med" for p in buckets["low"])

    def test_above_threshold_not_in_any_bucket(self, isolated_db):
        store_id = signup("Store", "O", "9876500404", "pass123")
        _add(store_id, "Healthy Med", "H01", 11)
        buckets = low_stock_service.get_low_stock_alerts(store_id)
        all_names = {p["name"] for v in buckets.values() for p in v}
        assert "Healthy Med" not in all_names

    def test_custom_threshold_used_for_bucketing(self, isolated_db):
        store_id = signup("Store", "O", "9876500405", "pass123")
        _add(store_id, "Custom Warn", "C01", 5, threshold=30)  # 5/30=17% -> WARNING
        _add(store_id, "Custom Low", "C02", 25, threshold=30)  # 25/30=83% -> LOW
        buckets = low_stock_service.get_low_stock_alerts(store_id)
        assert any(p["name"] == "Custom Warn" for p in buckets["warning"])
        assert any(p["name"] == "Custom Low" for p in buckets["low"])

    def test_effective_threshold_present_in_row_data(self, isolated_db):
        store_id = signup("Store", "O", "9876500406", "pass123")
        _add(store_id, "Test Med", "T01", 3)
        buckets = low_stock_service.get_low_stock_alerts(store_id)
        row = buckets["warning"][0]
        assert "effective_threshold" in row
        assert "quantity" in row


class TestMultiTenantIsolation:
    def test_stores_cannot_see_each_others_low_stock(self, isolated_db):
        store_a = signup("Store A", "O", "9876500407", "pass123")
        store_b = signup("Store B", "O", "9876500408", "pass123")
        _add(store_a, "A Item", "A01", 0)
        _add(store_b, "B Item", "B01", 0)
        buckets_a = low_stock_service.get_low_stock_alerts(store_a)
        names_a = {p["name"] for v in buckets_a.values() for p in v}
        assert "A Item" in names_a
        assert "B Item" not in names_a


class TestSearchFiltering:
    def test_search_by_name(self, isolated_db):
        store_id = signup("Store", "O", "9876500409", "pass123")
        _add(store_id, "Paracetamol", "P01", 0)
        _add(store_id, "Ibuprofen", "I01", 0)
        result = low_stock_service.get_low_stock_alerts(store_id, search_term="paracet")
        names = {p["name"] for v in result.values() for p in v}
        assert "Paracetamol" in names
        assert "Ibuprofen" not in names

    def test_search_by_batch(self, isolated_db):
        store_id = signup("Store", "O", "9876500410", "pass123")
        _add(store_id, "Med A", "BATCH99", 0)
        result = low_stock_service.get_low_stock_alerts(store_id, search_term="BATCH99")
        names = {p["name"] for v in result.values() for p in v}
        assert "Med A" in names


class TestLowStockUIRendersCorrectly:
    def test_page_loads_shows_severity_sections_and_qty_min(self, isolated_db):
        mobile = "9876500411"
        store_id = signup("UI Store", "Owner", mobile, "pass123")
        _add(store_id, "Out Of Stock", "U01", 0)
        _add(store_id, "Very Low", "U02", 3)

        at = AppTest.from_file("app.py", default_timeout=30)
        at.run()
        at.text_input[0].input(mobile)
        at.text_input[1].input("pass123")
        at.button[0].click()
        at.run()
        at.sidebar.radio[0].set_value("📦 Low Stock").run()

        assert len(at.exception) == 0
        headers = [m.value for m in at.markdown if "<h4" in (m.value or "")]
        assert any("#D32F2F" in h for h in headers), "Critical (red) header expected"
        rows_with_qty_min = [m.value for m in at.markdown if "Qty:" in (m.value or "") and "Min:" in (m.value or "")]
        assert len(rows_with_qty_min) >= 1

    def test_filter_narrows_to_one_section(self, isolated_db):
        mobile = "9876500412"
        store_id = signup("Filter UI Store", "Owner", mobile, "pass123")
        _add(store_id, "Out Of Stock", "F01", 0)
        _add(store_id, "Low Item", "F02", 8)

        at = AppTest.from_file("app.py", default_timeout=30)
        at.run()
        at.text_input[0].input(mobile)
        at.text_input[1].input("pass123")
        at.button[0].click()
        at.run()
        at.sidebar.radio[0].set_value("📦 Low Stock").run()

        critical_option = next(o for o in at.selectbox[0].options if "Out of Stock" in o)
        at.selectbox[0].set_value(critical_option).run()
        headers = [m.value for m in at.markdown if "<h4" in (m.value or "")]
        assert len(headers) == 1
        assert "#D32F2F" in headers[0]

    def test_empty_state_when_all_healthy(self, isolated_db):
        mobile = "9876500413"
        store_id = signup("Healthy Store", "Owner", mobile, "pass123")
        _add(store_id, "Healthy Med", "G01", 100)

        at = AppTest.from_file("app.py", default_timeout=30)
        at.run()
        at.text_input[0].input(mobile)
        at.text_input[1].input("pass123")
        at.button[0].click()
        at.run()
        at.sidebar.radio[0].set_value("📦 Low Stock").run()

        assert len(at.exception) == 0
        assert any("stocked" in (m.value or "").lower() for m in at.success)
