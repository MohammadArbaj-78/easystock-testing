"""Dashboard alert counts built from pre-fetched rows must equal the
counts from the normal (re-fetching) path."""
from datetime import date
from modules.alerts import service as alerts_service
from modules.products import repository as repo


def _mm_yy(offset_months):
    t = date.today()
    m = t.month - 1 + offset_months
    return f"{m % 12 + 1:02d}/{(t.year + m // 12) % 100:02d}"


def test_counts_from_rows_match_fetch_path(monkeypatch):
    rows = []
    pid = 0
    for off in (-5, -3, -2, -1, 0, 1, 2, 3, 6):
        for qty in (0, 4):
            pid += 1
            rows.append({"product_id": pid, "name": f"m{pid}", "batch_number": f"b{pid}",
                         "expiry_date": _mm_yy(off), "quantity": qty, "mrp": 1, "rate": 1})
    rows.append({"product_id": 99, "name": "bad", "batch_number": "x",
                 "expiry_date": "garbage", "quantity": 3, "mrp": 1, "rate": 1})
    monkeypatch.setattr(repo, "get_expired_products", lambda s: repo._filter_expired_rows(rows))
    monkeypatch.setattr(repo, "get_expiring_soon_products",
                        lambda s, within_days: repo._filter_expiring_soon_rows(rows, within_days))
    assert alerts_service.get_alert_counts(1) == alerts_service.get_alert_counts(1, rows=rows)
    assert sum(alerts_service.get_alert_counts(1, rows=rows).values()) > 0
