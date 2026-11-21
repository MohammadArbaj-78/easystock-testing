"""Quantity-0 mode: scanning an old bill after a new one (or the reverse) gives the same latest batch / expiry."""
from unittest.mock import patch

from modules.products import service


def _lot(batch, expiry, qty=0):
    return {"name": "Dolo 650", "batch_number": batch, "expiry_date": expiry, "quantity": qty,
            "mrp": "30", "rate": "20", "gst_percent": "12", "pack_size": "", "purchase_date": ""}


class _Db:
    """A one-medicine fake products table."""
    def __init__(self):
        self.rows, self.next_id = [], 1

    def get_all_products(self, store_id, search_term=None):
        return [dict(r) for r in self.rows]

    def create_product(self, store_id, data):
        row = dict(data, product_id=self.next_id, minimum_stock_threshold=None)
        self.next_id += 1
        self.rows.append(row)
        return row["product_id"]

    def update_product(self, store_id, product_id, data):
        for r in self.rows:
            if r["product_id"] == product_id:
                r.update(data)

    def get_product_by_id(self, store_id, product_id):
        return next((dict(r) for r in self.rows if r["product_id"] == product_id), None)


def _scan(db, *lots):
    with patch.object(service.products_repository, "get_all_products", db.get_all_products), \
         patch.object(service.products_repository, "create_product", db.create_product), \
         patch.object(service.products_repository, "update_product", db.update_product), \
         patch.object(service.products_repository, "get_product_by_id", db.get_product_by_id):
        for lot in lots:
            service.save_or_merge_invoice_lot(1, lot)


def test_new_then_old_keeps_latest():
    db = _Db()
    _scan(db, _lot("NEW1", "06/28"), _lot("OLD1", "03/27"))
    assert len(db.rows) == 1
    assert (db.rows[0]["batch_number"], db.rows[0]["expiry_date"]) == ("NEW1", "06/28")


def test_old_then_new_gives_same_result():
    db = _Db()
    _scan(db, _lot("OLD1", "03/27"), _lot("NEW1", "06/28"))
    assert len(db.rows) == 1
    assert (db.rows[0]["batch_number"], db.rows[0]["expiry_date"]) == ("NEW1", "06/28")


def test_many_bills_any_order_same_final_row():
    import itertools
    lots = [("A", "03/27"), ("B", "09/27"), ("C", "06/28")]
    for order in itertools.permutations(lots):
        db = _Db()
        _scan(db, *[_lot(b, e) for b, e in order])
        assert (db.rows[0]["batch_number"], db.rows[0]["expiry_date"]) == ("C", "06/28"), order


def test_real_quantity_mode_is_unchanged():
    """A row with stock is never replaced; a new batch becomes its own lot as before."""
    db = _Db()
    _scan(db, _lot("NEW1", "06/28", qty=10), _lot("OLD1", "03/27", qty=5))
    assert sorted(r["batch_number"] for r in db.rows) == ["NEW1", "OLD1"]


def test_expiry_is_later_helper():
    assert service._expiry_is_later("06/28", "03/27")
    assert service._expiry_is_later("Jun-2028", "12/27")
    assert not service._expiry_is_later("03/27", "06/28")
    assert not service._expiry_is_later("03/27", "03/27")
    assert not service._expiry_is_later("", "03/27")
    assert not service._expiry_is_later("junk", "03/27")
