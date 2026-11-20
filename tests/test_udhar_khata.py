"""Udhar Khata: customers, entries, balances, history, reminder link, screen state."""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.udhar import repository, service


@pytest.fixture
def sqlite_db(tmp_path):
    import core.database as database
    path = str(tmp_path / "t.db")
    with patch.object(database, "DATABASE_PATH", path):
        database.initialize_database()
        yield path


def _customer(store=1, name="Ramesh", mobile="9876543210"):
    return service.add_customer(store, name, mobile)["customer_id"]


def test_normalize_mobile():
    assert service.normalize_mobile("9876543210") == "9876543210"
    assert service.normalize_mobile("+91 98765-43210") == "9876543210"
    assert service.normalize_mobile("098765 43210") == "9876543210"
    for bad in ("12345", "5876543210", "", None, "98765432101234", "abcdefghij"):
        assert service.normalize_mobile(bad) is None


def test_parse_amount():
    assert service.parse_amount("1,250.50") == 1250.5
    assert service.parse_amount(10) == 10.0
    assert service.parse_amount("12.345") == 12.34          # at most 2 decimals
    for bad in (None, "", "0", "-5", "abc", "nan", "inf", True, 10**9):
        assert service.parse_amount(bad) is None


def test_add_customer_rules(sqlite_db):
    assert service.add_customer(1, " Ramesh   Kumar ", "98765 43210")["status"] == "added"
    assert service.get_customers(1)[0]["name"] == "Ramesh Kumar"
    assert service.add_customer(1, "Other", "9876543210")["status"] == "exists"
    assert service.add_customer(1, "x", "9876543211")["status"] == "bad_name"
    assert service.add_customer(1, "Suresh", "123")["status"] == "bad_mobile"
    assert service.add_customer(2, "Ramesh", "9876543210")["status"] == "added"       # other store: allowed


def test_database_duplicate_reported_as_exists(sqlite_db):
    _customer()
    with patch.object(repository, "list_customers", return_value=[]):                  # list was stale
        assert service.add_customer(1, "Ramesh", "9876543210")["status"] == "exists"


def test_balance_is_gave_minus_got(sqlite_db):
    cid = _customer()
    assert service.add_entry(1, cid, "gave", "500")["status"] == "added"
    assert service.add_entry(1, cid, "gave", 250.5, "Dolo 2 strip")["status"] == "added"
    assert service.add_entry(1, cid, "got", "300")["status"] == "added"
    customer = service.get_customers(1)[0]
    assert customer["balance"] == 450.5
    assert service.summary([customer]) == {"total": 450.5, "count": 1}


def test_entry_validation(sqlite_db):
    cid = _customer()
    assert service.add_entry(1, cid, "gave", "0")["status"] == "bad_amount"
    assert service.add_entry(1, cid, "gave", "abc")["status"] == "bad_amount"
    assert service.add_entry(1, cid, "lent", "5")["status"] == "bad_kind"
    assert service.add_entry(2, cid, "gave", "5")["status"] == "no_customer"           # another store's customer
    assert service.add_entry(1, 999, "gave", "5")["status"] == "no_customer"
    assert repository.list_entries(1, cid) == []


def test_history_running_balance_and_order(sqlite_db):
    from datetime import date
    cid = _customer()
    service.add_entry(1, cid, "gave", 500, "", date(2026, 11, 1))
    service.add_entry(1, cid, "got", 200, "", date(2026, 11, 5))
    service.add_entry(1, cid, "gave", 100, "", date(2026, 11, 9))
    balance = service.get_customers(1)[0]["balance"]
    history = service.get_history(1, cid, balance)
    assert [(h["kind"], h["amount"], h["balance_after"]) for h in history] == [
        ("gave", 100.0, 400.0), ("got", 200.0, 300.0), ("gave", 500.0, 500.0),
    ]


def test_customers_sorted_by_balance_then_name(sqlite_db):
    a = _customer(name="Anil", mobile="9000000001")
    b = _customer(name="Bharat", mobile="9000000002")
    _customer(name="Chetan", mobile="9000000003")
    service.add_entry(1, a, "gave", 100)
    service.add_entry(1, b, "gave", 900)
    assert [c["name"] for c in service.get_customers(1)] == ["Bharat", "Anil", "Chetan"]


def test_settled_and_advance_are_not_counted_as_owing(sqlite_db):
    a = _customer(name="Anil", mobile="9000000001")
    b = _customer(name="Bharat", mobile="9000000002")
    service.add_entry(1, a, "gave", 100)
    service.add_entry(1, a, "got", 100)
    service.add_entry(1, b, "got", 50)
    assert service.summary(service.get_customers(1)) == {"total": 0, "count": 0}


def test_delete_entry_changes_balance_and_is_store_scoped(sqlite_db):
    cid = _customer()
    service.add_entry(1, cid, "gave", 500)
    entry_id = repository.list_entries(1, cid)[0]["entry_id"]
    service.delete_entry(2, entry_id)                                                    # other store: nothing
    assert service.get_customers(1)[0]["balance"] == 500
    service.delete_entry(1, entry_id)
    assert service.get_customers(1)[0]["balance"] == 0


def test_customer_with_history_is_never_deleted(sqlite_db):
    cid = _customer()
    service.add_entry(1, cid, "gave", 10)
    assert service.delete_customer_if_unused(1, cid) is False
    assert len(service.get_customers(1)) == 1
    empty = _customer(name="Naya", mobile="9000000009")
    assert service.delete_customer_if_unused(1, empty) is True
    assert [c["name"] for c in service.get_customers(1)] == ["Ramesh"]


def test_reminder_message_and_link():
    message = service.reminder_message("Sharma Medical", "Ramesh", 1250.5)
    assert "Ramesh ji" in message and "Sharma Medical" in message and "₹1,250.5" in message
    url = service.whatsapp_url("9876543210", message)
    assert url.startswith("https://wa.me/919876543210?text=")
    assert " " not in url and "%E2%82%B9" in url


def test_money():
    assert service.money(100) == "₹100"
    assert service.money(1234.5) == "₹1,234.5"
    assert service.money(0) == "₹0"


def test_supabase_payloads():
    table = MagicMock()
    table.insert.return_value.execute.return_value.data = [{"customer_id": 4, "entry_id": 8}]
    with patch.object(repository, "ACTIVE_DB_BACKEND", "supabase"), patch.object(repository, "_table", return_value=table):
        assert repository.add_customer(3, "Ramesh", "9876543210") == 4
        table.insert.assert_called_with({"store_id": 3, "name": "Ramesh", "mobile": "9876543210"})
        assert repository.add_entry(3, 4, "gave", 10.0, None, "2026-11-18") == 8
        table.insert.assert_called_with({
            "store_id": 3, "customer_id": 4, "kind": "gave", "amount": 10.0,
            "note": None, "entry_date": "2026-11-18",
        })
        repository.delete_entry(3, 8)
        table.delete.return_value.eq.assert_called_with("store_id", 3)
        table.delete.return_value.eq.return_value.eq.assert_called_with("entry_id", 8)


def test_supabase_balance_read_is_rounded():
    table = MagicMock()
    table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"customer_id": 1, "name": "A", "mobile": "9000000001", "balance": "100.10000000001", "last_entry_date": None},
    ]
    with patch.object(repository, "ACTIVE_DB_BACKEND", "supabase"), patch.object(repository, "_table", return_value=table):
        assert repository.list_customers(3)[0]["balance"] == 100.1


def test_screen_state_flow(sqlite_db):
    from modules.udhar import ui
    state = {}
    with patch.object(ui, "st", types.SimpleNamespace(session_state=state)):
        assert ui._state(1)["customers"] == []
        cid = _customer()
        assert ui._state(1)["customers"] == []                       # kept until refreshed
        ui._refresh(1)
        assert ui._find_customer(1, cid)["name"] == "Ramesh"
        ui._open_customer(cid)
        assert state[ui._SELECTED] == cid
        service.add_entry(1, cid, "gave", 50)
        ui._refresh(1)
        assert [h["amount"] for h in ui._history(1, ui._find_customer(1, cid))] == [50.0]
        ui._back()
        assert ui._SELECTED not in state
        assert ui._find_customer(2, cid) is None                     # another store sees nothing


def test_customer_row_has_no_mobile_and_is_escaped():
    from modules.udhar import ui
    row = {"customer_id": 4, "name": "<b>Ra</b>mesh", "mobile": "9876543210", "balance": 250.0}
    text = ui._row_html(row)
    assert "9876543210" not in text and "<b>Ra" not in text and "ud-id-4" in text
    assert "Lena hai" in text and "₹250" in text
    assert "Barabar" in ui._row_html({**row, "balance": 0.0})
    assert "Advance" in ui._row_html({**row, "balance": -10.0})


def test_entry_row_shows_question_only_when_asking():
    from modules.udhar import ui
    entry = {"entry_id": 9, "kind": "gave", "amount": 100.0, "note": "Dolo <i>", "entry_date": "2026-11-20", "balance_after": 100.0}
    plain, asking = ui._entry_html(entry, False), ui._entry_html(entry, True)
    assert "ud-yes" not in plain and "ud-yes" in asking and "ud-id-9" in plain
    assert "<i>" not in plain and "−₹100" in plain and "20 Nov 2026" in plain


def test_wrong_number_clears_only_the_number_box():
    from modules.udhar import ui
    state = {}
    with patch.object(ui, "st", types.SimpleNamespace(session_state=state)):
        ui._bump(ui._NC_MOBILE_V)
        assert state[ui._NC_MOBILE_V] == 1 and ui._NC_NAME_V not in state      # name box keeps its key (and text)
