"""Diary: quantity (+/-) saving, agency picker with "Add agency", qty in the agency list / message."""
import sqlite3

import pytest

from modules.low_stock_diary import repository, service, ui


@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "diary.db")

    def connect():
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        return connection

    import core.database as database
    monkeypatch.setattr(database, "get_connection", connect)
    monkeypatch.setattr(repository, "ACTIVE_DB_BACKEND", "sqlite")
    return path


def test_parse_payload():
    assert service.parse_qty_payload("3;12:5,7:0") == {12: 5, 7: 0}
    assert service.parse_qty_payload("1;x:5,9:abc,4:2") == {4: 2}
    assert service.parse_qty_payload("1;3:-4") == {3: 0}
    assert service.parse_qty_payload("1;3:999999999") == {3: service.MAX_QTY}
    assert service.parse_qty_payload("") == {}
    assert service.parse_qty_payload(None) == {}


def test_quantities_are_saved_and_listed(db):
    a = service.add_medicine(1, "Crocin 1000mg Tablet")["diary_id"]
    b = service.add_medicine(1, "Paracetamol 500mg")["diary_id"]
    result = service.set_quantities(1, {a: 10, b: 3})
    assert result["status"] == "saved"
    rows = {row["diary_id"]: row for row in service.get_entries(1)}
    assert rows[a]["qty"] == 10 and rows[b]["qty"] == 3
    service.set_quantities(1, {a: 0})                    # 0 = not set
    rows = {row["diary_id"]: row for row in service.get_entries(1)}
    assert rows[a]["qty"] is None and rows[b]["qty"] == 3


def test_quantity_of_another_store_is_untouched(db):
    mine = service.add_medicine(1, "Dolo 650")["diary_id"]
    other = service.add_medicine(2, "Dolo 650")["diary_id"]
    service.set_quantities(1, {mine: 4, other: 9})
    assert service.get_entries(2)[0]["qty"] is None


def test_old_table_without_qty_column_gets_it(db):
    connection = sqlite3.connect(db)
    connection.execute(
        "CREATE TABLE low_stock_diary (diary_id INTEGER PRIMARY KEY AUTOINCREMENT, store_id INTEGER NOT NULL,"
        " name TEXT NOT NULL, name_key TEXT NOT NULL, agency_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP,"
        " UNIQUE (store_id, name_key))"
    )
    connection.execute("INSERT INTO low_stock_diary (store_id, name, name_key) VALUES (1, 'Old one', 'oldone')")
    connection.commit()
    connection.close()
    rows = service.get_entries(1)
    assert rows[0]["name"] == "Old one" and rows[0]["qty"] is None
    assert service.set_quantities(1, {rows[0]["diary_id"]: 2})["status"] == "saved"


def test_save_error_is_returned_not_raised(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("column qty does not exist")
    monkeypatch.setattr(repository, "set_quantities", boom)
    result = service.set_quantities(1, {1: 2})
    assert result["status"] == "error" and "qty" in result["error"]


def test_line_text_and_message():
    assert service.line_text({"name": "Crocin", "qty": 10}) == "Crocin - 10"
    assert service.line_text({"name": "Crocin", "qty": None}) == "Crocin"
    assert service.line_text({"name": "Crocin"}) == "Crocin"
    text = service.order_message("Ram Agency", [service.line_text({"name": "Crocin", "qty": 10}), "Dolo"])
    assert "1. Crocin - 10" in text and "2. Dolo" in text


def test_add_agency(monkeypatch):
    from modules.agencies import repository as agencies_repository
    seen = []
    monkeypatch.setattr(agencies_repository, "find_or_create_agency", lambda store_id, name: seen.append((store_id, name)) or 77)
    assert service.add_agency(5, "  New   Dhar  Medicose ") == {"status": "ok", "agency_id": 77, "name": "New Dhar Medicose"}
    assert seen == [(5, "New Dhar Medicose")]
    assert service.add_agency(5, " ")["status"] == "invalid"
    assert service.add_agency(5, "a")["status"] == "invalid"
    assert service.add_agency(5, "--")["status"] == "invalid"
    monkeypatch.setattr(agencies_repository, "find_or_create_agency", lambda *_a: (_ for _ in ()).throw(RuntimeError("down")))
    assert service.add_agency(5, "Good name")["status"] == "error"


def test_row_html_has_name_qty_and_ids():
    html_text = ui.row_html({"diary_id": 12, "name": "A <b>& B", "qty": 7}, selected=True)
    assert "lsd-id-12" in html_text and "lsd-sel" in html_text and "data-q='7'" in html_text
    assert "A &lt;b&gt;&amp; B" in html_text and "<span class='lsd-side'>7</span>" in html_text
    plain = ui.row_html({"diary_id": 3, "name": "Dolo", "qty": None})
    assert "data-q='0'" in plain and "<span class='lsd-side'></span>" in plain


def test_page_wiring_in_source():
    import inspect
    source = inspect.getsource(ui)
    assert "lsd-qmode" in source and "st-key-lsd_qsink" in source
    assert '"➕ Add agency"' in source and "Chunav hatao" in source
    assert "Is agency ki list me bhejo" not in source
