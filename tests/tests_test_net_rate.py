from modules.invoice_scan.review_service import net_rate_text


def test_free_pieces_reduce_rate():
    assert net_rate_text({"rate": 10, "qty": 10, "quantity": 12}) == "8.33"


def test_no_free_keeps_rate():
    assert net_rate_text({"rate": 10, "qty": 10, "quantity": 10}) == "10.00"


def test_blank_rate_is_blank():
    assert net_rate_text({"rate": "", "qty": 10, "quantity": 12}) == ""


def test_bad_numbers_do_not_crash():
    assert net_rate_text({"rate": "abc", "qty": "x", "quantity": None}) == ""
