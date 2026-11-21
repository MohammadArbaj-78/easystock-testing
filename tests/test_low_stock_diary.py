"""Low Stock Diary: storing, duplicates, deleting, store isolation, suggestions."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.low_stock_diary import repository, service


@pytest.fixture
def sqlite_db(tmp_path):
    import core.database as database
    path = str(tmp_path / "t.db")
    with patch.object(database, "DATABASE_PATH", path):
        database.initialize_database()
        yield path


def test_add_and_list_newest_first(sqlite_db):
    assert service.add_medicine(1, "  Dolo   650 ")["status"] == "added"
    assert service.add_medicine(1, "Telsar-H")["status"] == "added"
    names = [row["name"] for row in service.get_entries(1)]
    assert names == ["Telsar-H", "Dolo 650"]
    assert all(row["agency_id"] is None for row in service.get_entries(1))


def test_same_medicine_is_not_added_twice(sqlite_db):
    service.add_medicine(1, "Dolo 650")
    assert service.add_medicine(1, "DOLO-650")["status"] == "exists"
    assert len(service.get_entries(1)) == 1


def test_database_duplicate_is_reported_as_exists(sqlite_db):
    service.add_medicine(1, "Dolo 650")
    with patch.object(repository, "list_entries", return_value=[]):      # list was stale
        assert service.add_medicine(1, "Dolo 650")["status"] == "exists"


def test_invalid_name(sqlite_db):
    assert service.add_medicine(1, "ab")["status"] == "invalid"
    assert service.add_medicine(1, "123")["status"] == "invalid"
    assert service.get_entries(1) == []


def test_delete_only_that_row_and_only_own_store(sqlite_db):
    service.add_medicine(1, "Dolo 650")
    service.add_medicine(1, "Telsar-H")
    service.add_medicine(2, "Dolo 650")
    first = next(row for row in service.get_entries(1) if row["name"] == "Dolo 650")
    service.remove_medicines(2, [first["diary_id"]])                  # another store: nothing happens
    assert len(service.get_entries(1)) == 2
    service.remove_medicines(1, [first["diary_id"]])
    assert [row["name"] for row in service.get_entries(1)] == ["Telsar-H"]
    assert len(service.get_entries(2)) == 1


def test_list_survives_new_connection(sqlite_db):
    service.add_medicine(1, "Dolo 650")
    assert [row["name"] for row in repository.list_entries(1)] == ["Dolo 650"]


def test_store_names_group_lots_and_keep_zero_stock():
    catalog = [
        {"name": "Dolo 650", "quantity": 2}, {"name": "DOLO-650", "quantity": 3},
        {"name": "Telsar-H", "quantity": 0}, {"name": "", "quantity": 1},
    ]
    names = service.store_medicine_names(catalog)
    assert {item["name"]: item["quantity"] for item in names} == {"Dolo 650": 5, "Telsar-H": 0}


def test_suggest_store_first_then_master_then_new():
    names = [{"name": "Dolo 650", "quantity": 5}, {"name": "Telsar-H", "quantity": 0}]
    assert service.suggest("dolo", names)["kind"] == "store"
    assert service.suggest("telsar", names)["items"][0]["name"] == "Telsar-H"      # 0 stock is found too
    with patch.object(service.sales_service, "search_master_medicines", return_value=[{"name": "Crocin", "composition": "x"}]):
        assert service.suggest("croc", names)["kind"] == "master"
    with patch.object(service.sales_service, "search_master_medicines", return_value=[]):
        result = service.suggest("zzzmed", names)
        assert result["kind"] == "new" and result["name"] == "zzzmed"
        assert service.suggest("zz", names)["kind"] == "none"
        assert service.suggest("", names)["kind"] == "none"


def test_supabase_payload():
    from unittest.mock import MagicMock
    table = MagicMock()
    table.insert.return_value.execute.return_value.data = [{"diary_id": 9}]
    with patch.object(repository, "ACTIVE_DB_BACKEND", "supabase"), patch.object(repository, "_table", return_value=table):
        assert repository.add_entry(3, "Dolo 650", "dolo 650") == 9
        table.insert.assert_called_once_with({"store_id": 3, "name": "Dolo 650", "name_key": "dolo 650"})
        repository.delete_entries(3, [1, 2])
        table.delete.return_value.eq.assert_called_with("store_id", 3)
        table.delete.return_value.eq.return_value.in_.assert_called_with("diary_id", [1, 2])


# ---------------------------------------------------------------- screen state

def test_screen_add_delete_flow(sqlite_db):
    import types
    from modules.low_stock_diary import ui

    state = {}
    fake_st = types.SimpleNamespace(session_state=state)
    with patch.object(ui, "st", fake_st):
        assert ui._entries(1) == []
        ui._add(1, "Dolo 650")
        assert state[ui._FLASH][0] == "success" and state[ui._VERSION] == 1
        assert [row["name"] for row in ui._entries(1)] == ["Dolo 650"]      # list refreshed
        ui._add(1, "dolo-650")
        assert state[ui._FLASH][0] == "info" and len(ui._entries(1)) == 1
        ui._add(1, "ab")
        assert state[ui._FLASH][0] == "warning"
        ui._delete(1, ui._entries(1)[0]["diary_id"])
        assert ui._entries(1) == []
        assert ui._entries(2) == []                                          # another store: own list


def test_add_with_known_rows_does_not_read_the_list_and_returns_id(sqlite_db):
    with patch.object(repository, "list_entries", side_effect=AssertionError("must not read")):
        result = service.add_medicine(1, "Dolo 650", known_rows=[])
    assert result["status"] == "added" and isinstance(result["diary_id"], int)


def test_known_rows_duplicate_is_exists_without_database(sqlite_db):
    rows = [{"diary_id": 5, "name": "Dolo 650", "agency_id": None}]
    with patch.object(repository, "add_entry", side_effect=AssertionError("must not write")):
        assert service.add_medicine(1, "dolo-650", known_rows=rows)["status"] == "exists"


def test_stale_known_rows_still_safe_via_database(sqlite_db):
    service.add_medicine(1, "Dolo 650")
    assert service.add_medicine(1, "Dolo 650", known_rows=[])["status"] == "exists"


def _ids(store_id):
    return {row["name"]: row["diary_id"] for row in service.get_entries(store_id)}


def test_assign_to_agency_and_back(sqlite_db):
    service.add_medicine(1, "Dolo 650")
    service.add_medicine(1, "Telsar-H")
    ids = _ids(1)
    service.assign_to_agency(1, [ids["Dolo 650"]], 7)
    plain, by_agency = service.split_rows(service.get_entries(1))
    assert [row["name"] for row in plain] == ["Telsar-H"]
    assert [row["name"] for row in by_agency[7]] == ["Dolo 650"]
    service.return_to_diary(1, [ids["Dolo 650"]])
    plain, by_agency = service.split_rows(service.get_entries(1))
    assert len(plain) == 2 and by_agency == {}


def test_assign_only_touches_own_store(sqlite_db):
    service.add_medicine(1, "Dolo 650")
    service.add_medicine(2, "Dolo 650")
    other = _ids(2)["Dolo 650"]
    service.assign_to_agency(1, [other], 7)               # id belongs to store 2: nothing happens
    assert service.get_entries(2)[0]["agency_id"] is None


def test_agency_list_oldest_first_and_clear_only_that_agency(sqlite_db):
    for name in ["Dolo 650", "Telsar-H", "Pan 40"]:
        service.add_medicine(1, name)
    ids = _ids(1)
    service.assign_to_agency(1, [ids["Dolo 650"], ids["Telsar-H"]], 7)
    service.assign_to_agency(1, [ids["Pan 40"]], 8)
    assert [row["name"] for row in service.agency_list(1, 7)] == ["Dolo 650", "Telsar-H"]
    assert service.clear_agency_list(1, 7) == 2
    assert service.agency_list(1, 7) == []
    assert [row["name"] for row in service.agency_list(1, 8)] == ["Pan 40"]


def test_order_message_and_whatsapp_url():
    text = service.order_message("Sharma Agency", ["Dolo 650", "Pan 40"])
    assert "Sharma Agency" in text and "1. Dolo 650" in text and "2. Pan 40" in text
    url = service.whatsapp_url(text)
    assert url.startswith("whatsapp://send?text=") and " " not in url and "\n" not in url
