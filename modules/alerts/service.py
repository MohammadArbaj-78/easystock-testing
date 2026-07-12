"""
Expiry Alerts business logic.

This module deliberately adds NO new database queries. It reuses
modules.products.repository's existing get_expired_products and
get_expiring_soon_products - the same functions Dashboard already
depends on - and applies one business rule on top: bucketing each
product into its single most urgent applicable alert category, so a
product expiring in 5 days appears once, under "7 Days", not duplicated
under 15 and 30 days as well.

Kept separate from repository.py because "which single bucket does this
product belong to" is a product/business decision (and the kind of rule
that's reasonable to change later, e.g. if EasyStock wants overlapping
buckets for a different business type), not a data-storage concern - it
has no business being expressed as SQL.

Alert type identifiers and their colors/icons/labels now live in
config.alert_theme, the single app-wide source of truth, after a real
bug where the Dashboard's expiry warning card was built against a
second, conflicting color scheme. They are re-imported and re-exported
here (not just used internally) so existing code that imports
ALERT_TYPE_* or ALERT_TYPE_DISPLAY from this module - modules/alerts/ui.py
and the test suite - keeps working unchanged.
"""

from datetime import date

from modules.products import repository as products_repository
from config.settings import EXPIRY_ALERT_WINDOWS_DAYS
from config.alert_theme import (
    ALERT_TYPE_EXPIRED,
    ALERT_TYPE_7_DAYS,
    ALERT_TYPE_15_DAYS,
    ALERT_TYPE_30_DAYS,
    ALL_ALERT_TYPES,
    ALERT_TYPE_DISPLAY,
)



def _bucket_label_for_window(days: int) -> str:
    """Map a window size in days to its alert type identifier.

    Args:
        days: One of the values in EXPIRY_ALERT_WINDOWS_DAYS.

    Returns:
        The matching ALERT_TYPE_* constant.

    Raises:
        ValueError: If days doesn't match a configured window - a
            programming error (EXPIRY_ALERT_WINDOWS_DAYS and this
            mapping have drifted out of sync), not a user-facing one.
    """
    mapping = {7: ALERT_TYPE_7_DAYS, 15: ALERT_TYPE_15_DAYS, 30: ALERT_TYPE_30_DAYS}
    if days not in mapping:
        raise ValueError(
            f"No alert bucket defined for a {days}-day window. "
            f"EXPIRY_ALERT_WINDOWS_DAYS and modules/alerts/service.py's "
            f"bucket mapping must stay in sync."
        )
    return mapping[days]


def get_categorized_alerts(store_id: int) -> dict:
    """Fetch and bucket all expiry-relevant products for a store.

    Reuses products_repository.get_expired_products and
    get_expiring_soon_products - no new SQL is written here. Each
    non-expired product is assigned to exactly one bucket: the smallest
    configured window it falls within (e.g. a product expiring in 5
    days qualifies for the 7, 15, and 30 day windows, but is bucketed
    only under "7 Days", since that's the most urgent/specific window
    that applies).

    Args:
        store_id: The currently logged-in store's ID. Every call into
            the repository below is scoped by this - Alerts can only
            ever see this store's products, same as every other module.

    Returns:
        A dict keyed by ALERT_TYPE_* constants, each value a list of
        product dicts (product_id, name, batch_number, expiry_date,
        quantity) belonging to that bucket, sorted by expiry_date
        ascending within each bucket.
    """
    buckets = {alert_type: [] for alert_type in ALL_ALERT_TYPES}

    buckets[ALERT_TYPE_EXPIRED] = products_repository.get_expired_products(store_id)

    # Fetch the widest window once, then narrow it down in Python -
    # this avoids running three increasingly-narrow SQL queries against
    # the same table when one query (the 30-day window, which is a
    # superset of 7 and 15) already has everything needed.
    widest_window = max(EXPIRY_ALERT_WINDOWS_DAYS)
    all_expiring_soon = products_repository.get_expiring_soon_products(
        store_id, within_days=widest_window
    )

    today = date.today()
    sorted_windows = sorted(EXPIRY_ALERT_WINDOWS_DAYS)

    for product in all_expiring_soon:
        # Compute days until expiry using the canonical MM/YY parser.
        # Treat expiry as the last day of the expiry month so a product
        # with expiry "7/26" gets full credit for the whole of July 2026.
        try:
            from utils.validators import parse_expiry_month_year
            import calendar
            m, y = parse_expiry_month_year(product["expiry_date"])
            last_day = calendar.monthrange(y, m)[1]
            expiry = date(y, m, last_day)
        except ValueError:
            # Legacy ISO date fallback — safe to keep for old rows
            try:
                expiry = date.fromisoformat(product["expiry_date"])
            except ValueError:
                continue  # unparseable value; skip rather than crash

        days_until_expiry = (expiry - today).days

        for window_days in sorted_windows:
            if days_until_expiry <= window_days:
                bucket_key = _bucket_label_for_window(window_days)
                buckets[bucket_key].append(product)
                break

    for alert_type in buckets:
        buckets[alert_type].sort(key=lambda p: p["expiry_date"])

    return buckets


def get_filtered_alerts(store_id: int, alert_type: str = None, search_term: str = None) -> dict:
    """Get categorized alerts, optionally narrowed to one alert type
    and/or filtered by a name/batch search term.

    Args:
        store_id: The currently logged-in store's ID.
        alert_type: One of ALERT_TYPE_* to show only that bucket, or
            None to show all buckets.
        search_term: Optional text to filter products by, matched
            case-insensitively as a substring against name or
            batch_number.

    Returns:
        A dict in the same shape as get_categorized_alerts - buckets not
        matching the alert_type filter are present but empty, so the UI
        can render a consistent structure regardless of which filter is
        active.
    """
    all_buckets = get_categorized_alerts(store_id)

    if alert_type and alert_type in all_buckets:
        all_buckets = {
            key: (value if key == alert_type else [])
            for key, value in all_buckets.items()
        }

    if search_term and search_term.strip():
        term = search_term.strip().lower()
        all_buckets = {
            key: [
                product for product in products
                if term in product["name"].lower() or term in product["batch_number"].lower()
            ]
            for key, products in all_buckets.items()
        }

    return all_buckets


def get_alert_counts(store_id: int) -> dict:
    """Get just the count of products in each alert bucket, without
    fetching full product details - used for the filter dropdown's
    labels (e.g. "Expired (3)") so a store owner can see at a glance
    where attention is needed before even opening a bucket.

    Args:
        store_id: The currently logged-in store's ID.

    Returns:
        A dict keyed by ALERT_TYPE_*, values are integer counts.
    """
    buckets = get_categorized_alerts(store_id)
    return {alert_type: len(products) for alert_type, products in buckets.items()}
