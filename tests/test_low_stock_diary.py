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
