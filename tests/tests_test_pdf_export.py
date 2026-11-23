"""PDF records: Udhar Khata, Low Stock Diary, Agencies (+ the small download button)."""
import sqlite3
from unittest.mock import MagicMock

import pytest

reportlab = pytest.importorskip("reportlab")

from core import pdf_export
from modules.low_stock_diary import ui as diary_ui
from modules.udhar import repository as udhar_repository
from modules.udhar import service as udhar_service


def _is_pdf(data) -> bool:
    return isinstance(data, bytes) and data.startswith(b"%PDF") and b"%%EOF" in data[-20:]


CUSTOMERS = [
    {"customer_id": 1, "name": "Ramesh <Kumar> & Sons", "mobile": "9876543210", "balance": 1250.5, "last_entry_date": "2026-11-03"},
    {"customer_id": 2, "name": "Sunita (हिंदी)", "mobile": "9876543211", "balance": 0, "last_entry_date": None},
    {"customer_id": 3, "name": "Advance wala", "mobile": "9876543212", "balance": -200, "last_entry_date": "2026-11-04"},
]
ENTRIES = [
    {"entry_id": 1, "customer_id": 1, "kind": "gave", "amount": 1500.5, "note": "bill <1>", "entry_date": "2026-11-01"},
    {"entry_id": 2, "customer_id": 1, "kind": "got", "amount": 250, "note": None, "entry_date": "2026-11-03"},
    {"entry_id": 3, "customer_id": 3, "kind": "got", "amount": 200, "note": "", "entry_date": "2026-11-04"},
]


def test_udhar_pdf_builds_with_odd_names_and_empty_data():
    assert _is_pdf(pdf_export.build_udhar_pdf("Arbaj <Store>", CUSTOMERS, ENTRIES))
    assert _is_pdf(pdf_export.build_udhar_pdf("S", [], []))
    assert _is_pdf(pdf_export.build_udhar_pdf("S", CUSTOMERS, []))


def test_udhar_pdf_many_customers_runs_over_pages():
    many = [{"customer_id": i, "name": f"C{i}", "mobile": "9876543210", "balance": i, "last_entry_date": "2026-11-01"} for i in range(1, 150)]
    entries = [{"entry_id": i, "customer_id": i, "kind": "gave", "amount": i, "note": "x", "entry_date": "2026-11-01"} for i in range(1, 150)]
    data = pdf_export.build_udhar_pdf("S", many, entries)
    assert _is_pdf(data) and data.count(b"/Type /Page\n") + data.count(b"/Type /Page ") >= 3


def test_diary_pdf():
    plain = [{"name": "Paracetamol 500mg", "qty": None}, {"name": "Pacadon", "qty": 4}]
    groups = [("New Dhar Medicose", [{"name": "Crocin", "qty": 10}]), ("Empty", [])]
    assert _is_pdf(pdf_export.build_diary_pdf("S", plain, groups))
    assert _is_pdf(pdf_export.build_diary_pdf("S", [], []))


def test_agencies_pdf():
    agencies = [{"agency_id": 1, "agency_name": "New Dhar"}, {"agency_id": 2, "agency_name": "No bills"}]
    details = {1: {
        "bills": [{"invoice_date": "12/11/2026", "grand_total": 5200.5, "created_at": "2026-11-12 10:00:00"}],
        "payments": [{"amount": 4000, "paid_on": "2026-11-15", "created_at": "2026-11-15 11:00:00"}],
    }}
    assert _is_pdf(pdf_export.build_agencies_pdf("S", agencies, details))
    assert _is_pdf(pdf_export.build_agencies_pdf("S", [], {}))


def test_clean_text_and_money_and_dates():
    assert pdf_export.clean_text("Sunita (हिंदी)") == "Sunita (?????)"
    assert pdf_export.clean_text(None) == ""
    assert pdf_export.money(1234.5) == "Rs. 1,234.50"
    assert pdf_export._date_text("2026-11-03") == "03 Nov 2026"
    assert pdf_export._date_text("12/11/2026") == "12/11/2026"
    assert pdf_export._date_text(None) == "-"


def test_error_pdf_is_a_valid_pdf():
    assert _is_pdf(pdf_export._error_pdf("PDF nahi ban payi: bad (thing) \\ here"))


def test_button_makes_the_pdf_only_when_pressed_and_never_raises(monkeypatch):
    fake = MagicMock()
    import streamlit
    monkeypatch.setattr(streamlit, "download_button", fake, raising=False)
    calls = []

    def build():
        calls.append(1)
        return b"%PDF-1.4 fake %%EOF"

    pdf_export.pdf_button("Download", build, "Test", "t1")
    assert calls == []                                   # nothing is built while the screen is drawn
    kwargs = fake.call_args.kwargs
    assert kwargs["on_click"] == "ignore" and kwargs["mime"] == "application/pdf"
    assert kwargs["file_name"].startswith("EasyStock_Test_") and kwargs["file_name"].endswith(".pdf")
    assert kwargs["data"]() == b"%PDF-1.4 fake %%EOF" and calls == [1]

    def broken():
        raise RuntimeError("db down")

    pdf_export.pdf_button("Download", broken, "Test", "t2")
    assert _is_pdf(fake.call_args.kwargs["data"]())      # a one-page PDF that says what went wrong


@pytest.fixture()
def udhar_db(tmp_path, monkeypatch):
    path = str(tmp_path / "udhar.db")

    def connect():
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        return connection

    import core.database as database
    monkeypatch.setattr(database, "get_connection", connect)
    monkeypatch.setattr(udhar_repository, "ACTIVE_DB_BACKEND", "sqlite")


def test_udhar_service_builds_the_record_from_the_database(udhar_db):
    added = udhar_service.add_customer(1, "Ramesh", "9876543210")
    udhar_service.add_entry(1, added["customer_id"], "gave", 500)
    udhar_service.add_entry(1, added["customer_id"], "got", 200)
    other = udhar_service.add_customer(2, "Other store", "9876543211")
    udhar_service.add_entry(2, other["customer_id"], "gave", 999)
    entries = udhar_repository.list_all_entries(1)
    assert [e["amount"] for e in entries] == [500, 200]          # only this store's entries
    assert _is_pdf(udhar_service.build_pdf(1, "My Store"))


def test_diary_button_is_only_for_a_diary_with_rows(monkeypatch):
    shown = []
    monkeypatch.setattr(diary_ui.pdf_export, "pdf_button", lambda *a, **k: shown.append((a, k)))
    monkeypatch.setattr(diary_ui, "get_current_store_name", lambda: "S")
    monkeypatch.setattr(diary_ui, "get_cache_epoch", lambda _s: 0)
    monkeypatch.setattr(diary_ui, "_agency_names_cached", lambda _s, _e: [(7, "Ram Agency")])
    diary_ui._render_pdf_button(1, [])
    assert shown == []
    rows = [{"diary_id": 1, "name": "Dolo", "agency_id": None, "qty": 2}, {"diary_id": 2, "name": "Crocin", "agency_id": 7, "qty": None}]
    diary_ui._render_pdf_button(1, rows)
    build = shown[0][0][1]
    assert _is_pdf(build())
