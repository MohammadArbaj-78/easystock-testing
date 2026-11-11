"""Tests for keeping each scanned invoice's medicines under its agency
(table agency_medicines): cleaning, SQLite storage, Supabase payload,
and the hook in review_service.save_invoice_medicines."""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from modules.agencies import repository, service
from modules.invoice_scan import review_service


def test_clean_row_blank_and_invalid_become_none():
    row = service._clean_medicine_row(
        {"name": " Paracetamol ", "batch_number": "", "quantity": "10",
         "expiry_date": "", "mrp": "₹1,250.50", "rate": "abc"}
    )
    assert row == {"name": "Paracetamol", "batch_number": None, "quantity": 10,
                   "expiry_date": None, "mrp": 1250.5, "rate": None}


def test_clean_row_without_name_is_dropped():
    assert service._clean_medicine_row({"name": "  ", "quantity": 5}) is None


def test_number_rejects_negative_nan():
    assert service._number_or_none("-1") is None
    assert service._number_or_none("nan") is None
    assert service._number_or_none(None) is None


@pytest.fixture
def sqlite_db(tmp_path):
    import core.database as database
    path = str(tmp_path / "t.db")
    with patch.object(database, "DATABASE_PATH", path):
        database.initialize_database()
        yield path


def _make_store_and_agency(path):
    con = sqlite3.connect(path)
    con.execute("INSERT INTO stores (store_name, owner_name, mobile_number, password_hash) "
                "VALUES ('S', 'O', '9999999999', 'x')")
    con.execute("INSERT INTO agencies (store_id, agency_name, normalized_name) VALUES (1, 'A', 'a')")
    con.commit()
    con.close()
    return 1, 1


def test_sqlite_insert_roundtrip(sqlite_db):
    rows = [
        {"name": "A", "batch_number": "B1", "quantity": 12, "expiry_date": "2027-05",
         "mrp": 10.5, "rate": 7},
        {"name": "B", "batch_number": None, "quantity": None, "expiry_date": None,
         "mrp": None, "rate": None},
    ]
    with patch.object(repository, "ACTIVE_DB_BACKEND", "sqlite"):
        store_id, agency_id = _make_store_and_agency(sqlite_db)
        assert repository.add_invoice_medicines(store_id, agency_id, None, rows) == 2
        assert repository.add_invoice_medicines(store_id, agency_id, None, []) == 0
    con = sqlite3.connect(sqlite_db)
    got = con.execute(
        "SELECT name,batch_number,quantity,expiry_date,mrp,rate,bill_id FROM agency_medicines ORDER BY id"
    ).fetchall()
    assert got == [("A", "B1", 12.0, "2027-05", 10.5, 7.0, None),
                   ("B", None, None, None, None, None, None)]


def test_supabase_payload():
    table = MagicMock()
    client = MagicMock()
    client.table.return_value = table
    fake = MagicMock()
    fake.get_supabase_client.return_value = client
    with patch.object(repository, "ACTIVE_DB_BACKEND", "supabase"), \
         patch.dict(sys.modules, {"core.supabase_client": fake}):
        n = repository.add_invoice_medicines(
            3, 9, 4, [{"name": "A", "batch_number": "X", "quantity": 1,
                       "expiry_date": None, "mrp": 2, "rate": None}])
    assert n == 1
    client.table.assert_called_with("agency_medicines")
    sent = table.insert.call_args[0][0]
    assert sent == [{"store_id": 3, "agency_id": 9, "bill_id": 4, "name": "A",
                     "batch_number": "X", "quantity": 1, "expiry_date": None,
                     "mrp": 2, "rate": None}]


def test_record_never_raises_and_looks_up_agency():
    meds = [{"name": "A", "quantity": "5"}]
    with patch.object(service.agencies_repository, "find_or_create_agency", return_value=7) as f, \
         patch.object(service.agencies_repository, "add_invoice_medicines", return_value=1) as a:
        out = service.record_invoice_medicines(1, {"agency_name": "Sharma"}, meds)
    assert out == {"recorded": 1}
    f.assert_called_once_with(1, "Sharma")
    assert a.call_args[0][:3] == (1, 7, None)

    with patch.object(service.agencies_repository, "add_invoice_medicines",
                      side_effect=RuntimeError("table missing")):
        out = service.record_invoice_medicines(1, {}, meds, agency_id=2)
    assert out["recorded"] == 0 and "table missing" in out["error"]

    assert service.record_invoice_medicines(1, {}, meds)["recorded"] == 0
    assert service.record_invoice_medicines(1, {"agency_name": "x"}, [])["recorded"] == 0


def test_save_hook_once_per_session():
    st.session_state[review_service._SESSION_KEY] = {"invoice_header": {"agency_name": "S"}}
    meds = [{"name": "A"}]
    with patch.object(review_service, "get_medicines", return_value=meds), \
         patch("modules.products.service.save_or_merge_invoice_lot", return_value={"status": "saved"}), \
         patch("modules.agencies.service.record_bill_from_invoice_header",
               return_value={"recorded": True, "agency_id": 5, "bill_id": 8}), \
         patch("modules.agencies.service.record_invoice_medicines", return_value={"recorded": 1}) as rec:
        r1 = review_service.save_invoice_medicines(1)
        r2 = review_service.save_invoice_medicines(1)
    assert r1["agency_medicines"] == {"recorded": 1}
    assert rec.call_count == 1
    assert rec.call_args.kwargs == {"agency_id": 5, "bill_id": 8}
    assert r2["agency_medicines"] == {"recorded": 0}
    del st.session_state[review_service._SESSION_KEY]