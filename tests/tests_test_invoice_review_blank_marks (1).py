"""Review: "5%" GST is fine, "-" / "_" = empty on the bill, clear red reason when the bill is not added to the agency."""
from modules.invoice_scan import review_service, review_ui
from modules.products import service as products_service


def _row(**over):
    row = {"name": "Starvog GM 2", "batch_number": "M12FK2600", "expiry_date": "5/28",
           "quantity": "4", "mrp": "19", "rate": "14", "gst_percent": "5"}
    row.update(over)
    return row


def test_gst_with_or_without_percent_sign_is_valid():
    for value in ("5", "5%", "5 %", "12.5%"):
        assert review_service.validate_medicine(_row(gst_percent=value)) == [], value


def test_gst_junk_is_still_blocked():
    assert review_service.validate_medicine(_row(gst_percent="five"))
    assert review_service.validate_medicine(_row(gst_percent="5%%x"))


def test_dash_or_underscore_means_empty_for_mrp_rate_gst():
    for mark in ("-", "_", "--", "—"):
        assert review_service.validate_medicine(_row(mrp=mark, rate=mark, gst_percent=mark)) == [], mark


def test_blank_box_is_still_required():
    assert review_service.validate_medicine(_row(mrp=""))
    assert review_service.validate_medicine(_row(rate="   "))


def test_dash_or_underscore_means_empty_for_batch_and_expiry():
    for mark in ("-", "_", "--", "—"):
        assert review_service.validate_medicine(_row(batch_number=mark, expiry_date=mark)) == [], mark


def test_batch_and_expiry_boxes_still_required_and_checked():
    assert review_service.validate_medicine(_row(batch_number=""))
    assert review_service.validate_medicine(_row(expiry_date=""))
    assert review_service.validate_medicine(_row(expiry_date="13/45"))


def test_quantity_does_not_accept_a_dash():
    assert review_service.validate_medicine(_row(quantity="-"))
    assert review_service.validate_medicine(_row(quantity="_"))


def test_saved_lot_batch_and_expiry_marks_become_empty():
    lot = products_service._clean_invoice_lot_data(_row(batch_number="-", expiry_date="_"))
    assert lot["batch_number"] == "" and lot["expiry_date"] == ""
    lot = products_service._clean_invoice_lot_data(_row())
    assert lot["batch_number"] == "M12FK2600" and lot["expiry_date"] == "5/28"


def test_marks_do_not_raise_warnings():
    from modules.invoice_scan import validation
    rows = [_row(name="A", batch_number="-", expiry_date="-"), _row(name="B", batch_number="-", expiry_date="-")]
    for row in validation.validate_medicines(rows):
        assert "DUPLICATE_BATCH" not in row["_validation"]["flags"]
        assert "INVALID_EXPIRY_FORMAT" not in row["_validation"]["flags"]


def test_agency_medicines_keep_marks_as_empty(monkeypatch):
    from modules.agencies import service as agencies_service
    kept = {}
    monkeypatch.setattr(agencies_service, "record_invoice_medicines",
                        lambda store_id, header, medicines, **k: kept.setdefault("rows", medicines) and {"recorded": len(medicines)})
    review_service._SESSION_KEY and None
    review_service._finish_save(
        1, [_row(batch_number="-", expiry_date="_"), _row(name="B")], {}, 2, [], [], {}, {"agency_id": 1, "bill_id": 2},
    )
    first, second = kept["rows"]
    assert first["batch_number"] == "" and first["expiry_date"] == ""
    assert second["batch_number"] == "M12FK2600" and second["expiry_date"] == "5/28"


def test_saved_lot_values():
    lot = products_service._clean_invoice_lot_data(_row(mrp="-", rate="_", gst_percent="5%"))
    assert lot["mrp"] == 0.0 and lot["rate"] is None and lot["gst_percent"] == 5.0
    lot = products_service._clean_invoice_lot_data(_row(gst_percent="-"))
    assert lot["gst_percent"] is None and lot["mrp"] == 19.0 and lot["rate"] == 14.0


def test_negative_numbers_still_rejected():
    assert review_service.validate_medicine(_row(mrp="-5"))


def test_ledger_reason_message_is_clear():
    total = review_ui._ledger_not_saved_message("No valid grand total.")
    assert "NAHI" in total and "Grand total khali" in total and "stock me save ho gayi" in total
    assert "Agency ka naam khali" in review_ui._ledger_not_saved_message("No agency name.")
