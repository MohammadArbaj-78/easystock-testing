"""'Asli qty save karo' switch: stored per store; OFF saves invoice
medicines with quantity 0 and nothing else changes."""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from modules.store_settings import repository, service
from modules.invoice_scan import review_service


@pytest.fixture
def db(tmp_path):
    import core.database as database
    path = str(tmp_path / "t.db")
    with patch.object(database, "DATABASE_PATH", path), \
         patch.object(repository, "ACTIVE_DB_BACKEND", "sqlite"):
        database.initialize_database()
        con = sqlite3.connect(path)
        for n in (1, 2):
            con.execute("INSERT INTO stores (store_name, owner_name, mobile_number, password_hash) VALUES ('S','O',?,'x')", (str(n),))
        con.commit(); con.close()
        yield path


def test_default_is_on_and_value_is_kept_per_store(db):
    assert service.invoice_saves_real_quantity(1) is True      # never touched
    service.set_invoice_saves_real_quantity(1, False)
    assert service.invoice_saves_real_quantity(1) is False
    assert service.invoice_saves_real_quantity(2) is True      # other store unaffected
    service.set_invoice_saves_real_quantity(1, True)
    assert service.invoice_saves_real_quantity(1) is True
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM store_app_settings WHERE store_id=1").fetchone()[0] == 1


def test_read_failure_keeps_real_quantity():
    with patch.object(repository, "get_save_real_qty", side_effect=RuntimeError("no table")):
        assert service.invoice_saves_real_quantity(1) is True


def test_supabase_roundtrip():
    table = MagicMock()
    client = MagicMock(); client.table.return_value = table
    fake = MagicMock(); fake.get_supabase_client.return_value = client
    with patch.object(repository, "ACTIVE_DB_BACKEND", "supabase"), \
         patch.dict(sys.modules, {"core.supabase_client": fake}):
        service.set_invoice_saves_real_quantity(5, False)
        sent = table.upsert.call_args[0][0]
        assert sent["store_id"] == 5 and sent["save_real_qty"] is False
        assert table.upsert.call_args.kwargs == {"on_conflict": "store_id"}
        sel = table.select.return_value.eq.return_value.limit.return_value.execute
        sel.return_value.data = [{"save_real_qty": False}]
        assert service.invoice_saves_real_quantity(5) is False
        sel.return_value.data = []
        assert service.invoice_saves_real_quantity(5) is True


def _save(real):
    st.session_state[review_service._SESSION_KEY] = {"invoice_header": {}}
    rows = [{"name": "A", "batch_number": "B1", "expiry_date": "2027-01", "quantity": "12",
             "mrp": "10", "rate": "7", "gst_percent": "12", "pack_size": "10"}]
    seen = []
    with patch.object(review_service, "get_medicines", return_value=rows), \
         patch("modules.store_settings.service.invoice_saves_real_quantity", return_value=real), \
         patch("modules.products.service.save_or_merge_invoice_lot",
               side_effect=lambda sid, lot: seen.append(lot) or {"status": "created", "product_id": 1}), \
         patch("modules.agencies.service.record_bill_from_invoice_header", return_value={"recorded": False}), \
         patch("modules.agencies.service.record_invoice_medicines", return_value={"recorded": 0}):
        review_service.save_invoice_medicines(1)
    del st.session_state[review_service._SESSION_KEY]
    return seen[0]


def test_switch_off_zeroes_only_quantity():
    on, off = _save(True), _save(False)
    assert on["quantity"] == "12" and off["quantity"] == 0
    assert {k: v for k, v in on.items() if k != "quantity"} == {k: v for k, v in off.items() if k != "quantity"}