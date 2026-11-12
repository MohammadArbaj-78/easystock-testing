"""Agency screen: live-linked medicines list, one-shot detail loading,
lazy bill photos."""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.agencies import repository, service


@pytest.fixture
def db(tmp_path):
    import core.database as database
    path = str(tmp_path / "t.db")
    with patch.object(database, "DATABASE_PATH", path), \
         patch.object(repository, "ACTIVE_DB_BACKEND", "sqlite"):
        database.initialize_database()
        con = sqlite3.connect(path)
        con.execute("INSERT INTO stores (store_name, owner_name, mobile_number, password_hash) VALUES ('S','O','1','x')")
        con.execute("INSERT INTO agencies (store_id, agency_name, normalized_name) VALUES (1,'A1','a1')")
        con.execute("INSERT INTO agencies (store_id, agency_name, normalized_name) VALUES (1,'A2','a2')")
        con.commit(); con.close()
        yield path


def _products(*rows):
    return [dict(product_id=i, name=n, batch_number=b, expiry_date=e, quantity=q, mrp=1, rate=1)
            for i, n, b, e, q in rows]


def _keep(agency_id, product_id, name, batch, expiry):
    repository.add_invoice_medicines(1, agency_id, None, [
        {"name": name, "batch_number": batch, "quantity": 5, "expiry_date": expiry,
         "mrp": 1, "rate": 1, "product_id": product_id}])


def _index(products):
    fake = MagicMock()
    fake.search_products.return_value = products
    with patch.dict(sys.modules, {"modules.products.service": fake}), \
         patch("modules.products.service", fake, create=True):
        import modules.products as pkg
        with patch.object(pkg, "service", fake, create=True):
            return service.get_agency_medicines_by_agency(1)


def test_live_qty_deleted_and_sorted(db):
    _keep(1, 10, "Zinc", "B1", "2027-01")
    _keep(1, 11, "Alpha", "B2", "2027-02")
    _keep(1, 12, "Gone", "B3", "2027-03")
    prods = _products((10, "Zinc", "B1", "2027-01", 99), (11, "Alpha", "B2", "2027-02", 7))
    idx = _index(prods)
    assert [p["name"] for p in idx[1]] == ["Alpha", "Zinc"]      # sorted, deleted one hidden
    assert idx[1][1]["quantity"] == 99                            # live product qty


def test_fallback_name_batch_expiry_and_dedupe_latest_agency(db):
    _keep(1, None, "Dolo", "B9", "2027-05")       # older, no product_id
    _keep(2, 20, "Dolo", "B9", "2027-05")         # newer, other agency, same product
    prods = _products((20, "Dolo", "B9", "2027-05", 3))
    idx = _index(prods)
    assert 1 not in idx and [p["product_id"] for p in idx[2]] == [20]
    # without the newer row, the unlinked row matches by name+batch+expiry
    with sqlite3.connect(db) as con:
        con.execute("DELETE FROM agency_medicines WHERE agency_id=2")
    assert [p["product_id"] for p in _index(prods)[1]] == [20]


def test_search_and_paging():
    items = [{"name": f"Med{i}", "batch_number": f"X{i}"} for i in range(25)]
    page = service.search_agency_medicines(items, "", 10)
    assert len(page["items"]) == 10 and page["total"] == 25
    assert service.search_agency_medicines(items, "x24", 10)["total"] == 1
    assert service.search_agency_medicines(items, "med2", 10)["total"] == 6


def test_all_details_single_pass(db):
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO agency_bills (store_id, agency_id, invoice_date, grand_total) VALUES (1,1,'2026-01-01',100)")
        con.execute("INSERT INTO agency_bills (store_id, agency_id, invoice_date, grand_total) VALUES (1,2,'2026-01-02',50)")
        con.execute("INSERT INTO agency_payments (store_id, agency_id, amount) VALUES (1,1,30)")
    d = service.get_all_agency_details(1)
    assert d[1]["balance"] == 70 and d[2]["balance"] == 50
    old = service.get_agency_detail(1, 1)
    assert [b["bill_id"] for b in d[1]["bills"]] == [b["bill_id"] for b in old["bills"]]
    assert [p["payment_id"] for p in d[1]["payments"]] == [p["payment_id"] for p in old["payments"]]
    assert (d[1]["total_billed"], d[1]["total_paid"]) == (old["total_billed"], old["total_paid"])


def test_old_sqlite_table_gets_product_id_column(tmp_path):
    import core.database as database
    path = str(tmp_path / "old.db")
    with patch.object(database, "DATABASE_PATH", path):
        database.initialize_database()
        con = sqlite3.connect(path)
        con.execute("DROP TABLE agency_medicines")
        con.execute("CREATE TABLE agency_medicines (id INTEGER PRIMARY KEY AUTOINCREMENT, store_id INTEGER NOT NULL, agency_id INTEGER NOT NULL, bill_id INTEGER, name TEXT NOT NULL, batch_number TEXT, quantity REAL, expiry_date TEXT, mrp REAL, rate REAL, created_at TEXT NOT NULL DEFAULT (datetime('now')))")
        con.commit(); con.close()
        database.initialize_database()
        cols = [r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(agency_medicines)")]
    assert "product_id" in cols


def test_supabase_insert_retries_without_product_id():
    table = MagicMock()
    table.insert.return_value.execute.side_effect = [Exception("no column product_id"), None]
    client = MagicMock(); client.table.return_value = table
    fake = MagicMock(); fake.get_supabase_client.return_value = client
    with patch.object(repository, "ACTIVE_DB_BACKEND", "supabase"), \
         patch.dict(sys.modules, {"core.supabase_client": fake}):
        n = repository.add_invoice_medicines(1, 1, None, [{"name": "A", "product_id": 4}])
    assert n == 1
    first, second = (c[0][0][0] for c in table.insert.call_args_list)
    assert first["product_id"] == 4 and "product_id" not in second


def test_ui_page_renders_lazily():
    from modules.agencies import ui
    st = MagicMock()
    st.session_state = {}
    st.columns.side_effect = lambda spec, **k: [MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))]
    st.cache_data = lambda *a, **k: (lambda f: f) if not (a and callable(a[0])) else a[0]
    st.toggle.return_value = False
    ledger = [{"agency_id": 1, "agency_name": "A1", "balance": 70.0}]
    with patch.object(ui, "st", st), \
         patch.object(ui, "get_current_store_id", return_value=1), \
         patch.object(ui, "get_cache_epoch", return_value=0), \
         patch.object(ui, "_get_agency_ledger_cached", return_value=ledger), \
         patch.object(ui, "_get_all_agency_details_cached", return_value={1: {
             "bills": [{"bill_id": 5, "invoice_date": "d", "grand_total": 1.0, "image_path": "p"}],
             "payments": [], "total_billed": 1, "total_paid": 0, "balance": 1}}), \
         patch.object(ui, "_get_agency_medicines_cached") as meds, \
         patch.object(ui, "_get_bill_image_urls_cached", return_value={"p": "https://x/y?a=1&b=2"}) as urls:
        ui.render_agencies_page()
    meds.assert_not_called()          # medicines untouched until the switch is on
    urls.assert_called_once_with(("p",))      # ONE call for all photos
    shown = [c.args[0] for c in st.markdown.call_args_list if "<img" in str(c.args[0])]
    assert shown and 'loading="lazy"' in shown[0] and "a=1&amp;b=2" in shown[0]
    st.container.assert_called_with(key="agency_card_1")


def test_medicine_rows_work_without_id_column():
    table = MagicMock()
    q = table.select.return_value.eq.return_value
    q.range.return_value.execute.return_value.data = [
        {"agency_id": 1, "name": "Old", "batch_number": "a", "expiry_date": "x"},
        {"agency_id": 2, "name": "New", "batch_number": "b", "expiry_date": "y"},
    ]
    client = MagicMock(); client.table.return_value = table
    fake = MagicMock(); fake.get_supabase_client.return_value = client
    with patch.object(repository, "ACTIVE_DB_BACKEND", "supabase"), \
         patch.dict(sys.modules, {"core.supabase_client": fake}):
        rows = repository.get_medicine_rows_for_store(1)
    assert [r["name"] for r in rows] == ["New", "Old"] and rows[0]["product_id"] is None
    table.select.assert_called_with("*")


def test_bulk_signed_urls():
    from core import supabase_storage as s
    client = MagicMock()
    client.storage.from_.return_value.create_signed_urls.return_value = [
        {"path": "a", "signedURL": "u1", "error": None}, {"path": "b", "signedURL": None, "error": "x"}]
    fake = MagicMock(); fake.get_supabase_client.return_value = client
    with patch.dict(sys.modules, {"core.supabase_client": fake}):
        assert s.get_invoice_image_urls(["a", "b", "a", None]) == {"a": "u1"}
        client.storage.from_.return_value.create_signed_urls.assert_called_once_with(["a", "b"], 900)
        client.storage.from_.return_value.create_signed_urls.side_effect = RuntimeError
        assert s.get_invoice_image_urls(["a"]) == {}
    assert s.get_invoice_image_urls([]) == {}