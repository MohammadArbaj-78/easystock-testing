"""Agency WhatsApp number (ask once), diary pick sends at once, WhatsApp / SMS bill text."""
import re
from unittest.mock import patch

from modules.low_stock_diary import repository, service
from modules.sales import bill_service


def test_whatsapp_url_with_and_without_number():
    assert service.whatsapp_url("Hi A", "9876543210").startswith("whatsapp://send?phone=919876543210&text=Hi")
    assert service.whatsapp_url("Hi A") == "whatsapp://send?text=Hi%20A"


def test_save_agency_mobile_validates_and_normalizes():
    with patch.object(repository, "set_agency_mobile") as save:
        assert service.save_agency_mobile(1, 5, "+91 98765-43210") == {"status": "saved", "mobile": "9876543210"}
        save.assert_called_once_with(1, 5, "9876543210")
        assert service.save_agency_mobile(1, 5, "12345")["status"] == "bad_mobile"
        assert save.call_count == 1


def test_save_failure_is_reported_not_raised():
    with patch.object(repository, "set_agency_mobile", side_effect=RuntimeError("no table")):
        assert service.save_agency_mobile(1, 5, "9876543210")["status"] == "error"


def test_missing_table_means_no_numbers():
    with patch.object(repository, "list_agency_mobiles", side_effect=RuntimeError("no table")):
        assert service.agency_mobiles(1) == {}


def test_sqlite_mobile_roundtrip(tmp_path):
    import sqlite3
    from contextlib import contextmanager
    path = str(tmp_path / "t.db")

    @contextmanager
    def conn():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    with patch("core.database.get_connection", conn), patch.object(repository, "ACTIVE_DB_BACKEND", "sqlite"):
        assert repository.list_agency_mobiles(1) == {}
        repository.set_agency_mobile(1, 7, "9876543210")
        repository.set_agency_mobile(1, 7, "9123456789")          # change = update, not a second row
        repository.set_agency_mobile(2, 7, "9000000000")
        assert repository.list_agency_mobiles(1) == {7: "9123456789"}


def test_bill_message_text():
    line = {"name": "Dolo 650", "kind": "other", "qty": 2, "mrp": 30.0, "pack": None, "lots": [], "raw_lots": []}
    with patch.object(bill_service, "line_amount", return_value=60.0), \
         patch.object(bill_service, "quantity_text", return_value="2"):
        text = bill_service.bill_message("Shree Medical", [line], {"name": "Ramesh"})
    assert "*Shree Medical*" in text and "Customer: Ramesh" in text
    assert "1. Dolo 650 x 2 = ₹60" in text and "Total: ₹60" in text


def test_bill_message_real_pricing():
    lines = [{"name": "Dolo 650", "kind": "other", "qty": 2, "mrp": 30.0},
             {"name": "Crocin", "kind": "other", "qty": 3, "mrp": 10.5, "pack": 10}]
    text = bill_service.bill_message("Shree Medical", lines, {})
    assert "1. Dolo 650 x 2 = ₹60" in text
    assert "Total: " in text and "Customer" not in text
