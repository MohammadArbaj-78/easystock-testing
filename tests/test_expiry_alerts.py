"""
Tests for Module 6 (Expiry Alerts): bucketing logic, filter, search,
multi-tenant isolation, and real UI behavior via Streamlit's AppTest.
"""

from datetime import date, timedelta

import pytest
from streamlit.testing.v1 import AppTest

from core.database import initialize_database
from core.auth import signup
from modules.products import service as products_service
from modules.alerts import service as alerts_service


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Provide a fresh, isolated SQLite database per test.

    Patches core.database's module-level DATABASE_PATH/DATA_DIR
    directly (not config.settings'), since core.database imported those
    values by value at module load time - patching config.settings
    after that import has no effect on the already-bound names actually
    used inside get_connection().
    """
    import core.database as database_module

    db_path = tmp_path / "test_easystock.db"
    monkeypatch.setattr(database_module, "DATABASE_PATH", str(db_path))
    monkeypatch.setattr(database_module, "DATA_DIR", str(tmp_path))
    initialize_database()
    return db_path


def _add_product_expiring_in(store_id: int, name: str, batch: str, days_from_today: int, quantity: int = 10) -> int:
    """Helper to create a product expiring a given number of days from
    today, including the past - add_product blocks past expiry dates by
    design, so a past date is set via a follow-up edit instead.
    """
    expiry = date.today() + timedelta(days=days_from_today)
    if days_from_today < 0:
        product_id = products_service.add_product(store_id, {
            "name": name, "batch_number": batch,
            "expiry_date": date.today() + timedelta(days=1),
            "quantity": quantity, "mrp": 10.0,
            "_minimum_stock_threshold_enabled": False, "minimum_stock_threshold": None,
        })
        products_service.edit_product(store_id, product_id, {
            "name": name, "batch_number": batch, "expiry_date": expiry,
            "quantity": quantity, "mrp": 10.0,
            "_minimum_stock_threshold_enabled": False, "minimum_stock_threshold": None,
        })
        return product_id
    return products_service.add_product(store_id, {
        "name": name, "batch_number": batch, "expiry_date": expiry,
        "quantity": quantity, "mrp": 10.0,
        "_minimum_stock_threshold_enabled": False, "minimum_stock_threshold": None,
    })


class TestBucketingLogic:
    """Verifies each product lands in exactly one alert bucket - its
    single most urgent applicable window."""

    def test_boundaries_are_inclusive_and_single_bucket(self, isolated_db):
        store_id = signup("Boundary Store", "Owner", "9876500001", "pass123")

        _add_product_expiring_in(store_id, "Already Expired", "X01", -5)
        _add_product_expiring_in(store_id, "Expires Today", "X02", 0)
        _add_product_expiring_in(store_id, "Exactly 7", "X03", 7)
        _add_product_expiring_in(store_id, "8 Days", "X04", 8)
        _add_product_expiring_in(store_id, "Exactly 15", "X05", 15)
        _add_product_expiring_in(store_id, "16 Days", "X06", 16)
        _add_product_expiring_in(store_id, "Exactly 30", "X07", 30)
        _add_product_expiring_in(store_id, "31 Days", "X08", 31)

        buckets = alerts_service.get_categorized_alerts(store_id)
        names = {k: {p["name"] for p in v} for k, v in buckets.items()}

        assert "Already Expired" in names["expired"]
        assert "Expires Today" in names["15_days"]
        assert "Exactly 7" in names["15_days"]
        assert "8 Days" in names["15_days"]
        assert "Exactly 15" in names["15_days"]
        assert "16 Days" in names["30_days"]
        assert "16 Days" not in names["15_days"]
        assert "Exactly 30" in names["30_days"]
        assert "31 Days" not in names["expired"] | names["15_days"] | names["30_days"]

    def test_product_appears_in_only_one_bucket(self, isolated_db):
        store_id = signup("Single Bucket Store", "Owner", "9876500002", "pass123")
        _add_product_expiring_in(store_id, "Five Day Item", "S01", 5)

        buckets = alerts_service.get_categorized_alerts(store_id)
        appearances = sum(
            1 for products in buckets.values()
            if any(p["name"] == "Five Day Item" for p in products)
        )
        assert appearances == 1


class TestMultiTenantIsolation:
    def test_stores_cannot_see_each_others_alerts(self, isolated_db):
        store_a = signup("Store A", "Owner A", "9876500003", "pass123")
        store_b = signup("Store B", "Owner B", "9876500004", "pass123")

        _add_product_expiring_in(store_a, "Store A Item", "A01", -1)
        _add_product_expiring_in(store_b, "Store B Item", "B01", -1)

        buckets_a = alerts_service.get_categorized_alerts(store_a)
        names_a = {p["name"] for p in buckets_a["expired"]}
        assert "Store A Item" in names_a
        assert "Store B Item" not in names_a


class TestFilterAndSearch:
    def test_filter_by_single_alert_type(self, isolated_db):
        store_id = signup("Filter Store", "Owner", "9876500005", "pass123")
        _add_product_expiring_in(store_id, "Expired Item", "F01", -1)
        _add_product_expiring_in(store_id, "Soon Item", "F02", 5)

        filtered = alerts_service.get_filtered_alerts(store_id, alert_type="expired")
        assert len(filtered["expired"]) == 1
        assert len(filtered["15_days"]) == 0

    def test_search_matches_name_and_batch(self, isolated_db):
        store_id = signup("Search Store", "Owner", "9876500006", "pass123")
        _add_product_expiring_in(store_id, "Paracetamol", "BATCH99", 5)

        by_name = alerts_service.get_filtered_alerts(store_id, search_term="paracet")
        assert any(p["name"] == "Paracetamol" for v in by_name.values() for p in v)

        by_batch = alerts_service.get_filtered_alerts(store_id, search_term="BATCH99")
        assert any(p["name"] == "Paracetamol" for v in by_batch.values() for p in v)


class TestExpiryAlertsUIRendersCorrectly:
    """Real Streamlit AppTest-driven checks - not just service-layer
    logic - confirming the page actually renders correctly end-to-end."""

    def test_page_loads_without_exceptions_and_shows_correct_counts(self, isolated_db):
        mobile = "9876500007"
        store_id = signup("UI Test Store", "Owner", mobile, "pass123")
        _add_product_expiring_in(store_id, "Expired Med", "U01", -1)
        _add_product_expiring_in(store_id, "Soon Med", "U02", 5)

        at = AppTest.from_file("app.py", default_timeout=30)
        at.run()
        at.text_input[0].input(mobile)
        at.text_input[1].input("pass123")
        at.button[0].click()
        at.run()
        at.sidebar.radio[0].set_value("⏰ Expiry Alerts").run()

        assert len(at.exception) == 0

        headers = [m.value for m in at.markdown if "<h4" in (m.value or "")]
        assert any("Expired (1)" in h for h in headers)
        assert any("Expiring in 15 Days (1)" in h for h in headers)

    def test_selecting_filter_narrows_visible_sections(self, isolated_db):
        mobile = "9876500008"
        store_id = signup("Filter UI Store", "Owner", mobile, "pass123")
        _add_product_expiring_in(store_id, "Expired Med", "U03", -1)
        _add_product_expiring_in(store_id, "Soon Med", "U04", 5)

        at = AppTest.from_file("app.py", default_timeout=30)
        at.run()
        at.text_input[0].input(mobile)
        at.text_input[1].input("pass123")
        at.button[0].click()
        at.run()
        at.sidebar.radio[0].set_value("⏰ Expiry Alerts").run()

        at.selectbox[0].set_value("🔴 Expired (1)").run()
        headers = [m.value for m in at.markdown if "<h4" in (m.value or "")]
        assert len(headers) == 1
        assert "Expired" in headers[0]
