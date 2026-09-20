"""
Dashboard business logic.

This service answers one question: "what are this store's current
inventory health numbers?" It contains no SQL - it calls
modules.products.repository for data and applies the business rules
(what counts as "expiring soon", how metrics are packaged) on top.

Kept separate from repository.py because "how is data stored and
fetched" (repository) and "what do these numbers mean for the business"
(service) are different concerns that change for different reasons - a
future change to the expiry window default shouldn't require touching
SQL, and a future schema change shouldn't require touching this file.

Imports streamlit only to read the Low Stock page's already-existing
session-state selection (see get_dashboard_metrics) - there is
otherwise no Streamlit code in this file.
"""

from core.session import get_current_low_stock_minimum


from modules.products import repository as products_repository
from config.settings import DASHBOARD_EXPIRY_SOON_DAYS


def get_dashboard_metrics(store_id: int) -> dict:
    """Compute the four headline metrics for a store's dashboard.

    Args:
        store_id: The currently logged-in store's ID. Callers must
            obtain this from core.session.get_current_store_id() - this
            function does not look it up itself, keeping the
            "where does store identity come from" decision in exactly
            one place in the codebase.

    Returns:
        A dict with keys:
            total_products (int)
            expiring_soon_count (int)
            expiring_soon_items (list of dict)
            expired_count (int)
            expired_items (list of dict)
            low_stock_count (int)
            low_stock_items (list of dict)

        Counts and item lists are both returned so the UI can show a
        number on the metric card and, optionally, a detail list below
        it without a second round-trip to the service.

        A returned/zeroed medicine (quantity == 0, see
        modules.products.service.return_medicine) is excluded from
        expired_items/expiring_soon_items and their counts here, the
        same quantity-0 exclusion modules.alerts.service.get_categorized_alerts
        already applies to the separate Expiry Alerts page - the two
        pages read the same underlying repository data and must agree.
        It stays in the database (and in Product Management) untouched;
        this only affects which items surface as a dashboard alert.
        Low Stock is intentionally unaffected by this filter - a
        quantity-0 product is still meaningfully "low stock" and
        low_stock_items/low_stock_count are unchanged.
    """
    snapshot = products_repository.get_dashboard_snapshot(
        store_id,
        within_days=DASHBOARD_EXPIRY_SOON_DAYS,
        low_stock_global_minimum=get_current_low_stock_minimum(),
    )

    total_products = snapshot["total_products"]

    expired_items = [
        item for item in snapshot["expired_items"]
        if item["quantity"] != 0
    ]

    expiring_soon_items = [
        item for item in snapshot["expiring_soon_items"]
        if item["quantity"] != 0
    ]

    low_stock_items = snapshot["low_stock_items"]

    return {
        "total_products": total_products,
        "expiring_soon_count": len(expiring_soon_items),
        "expiring_soon_items": expiring_soon_items,
        "expired_count": len(expired_items),
        "expired_items": expired_items,
        "low_stock_count": len(low_stock_items),
        "low_stock_items": low_stock_items,
    }
