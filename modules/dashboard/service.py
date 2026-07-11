"""
Dashboard business logic.

This service answers one question: "what are this store's current
inventory health numbers?" It contains no Streamlit code and no SQL -
it calls modules.products.repository for data and applies the
business rules (what counts as "expiring soon", how metrics are
packaged) on top.

Kept separate from repository.py because "how is data stored and
fetched" (repository) and "what do these numbers mean for the business"
(service) are different concerns that change for different reasons - a
future change to the expiry window default shouldn't require touching
SQL, and a future schema change shouldn't require touching this file.
"""

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
    """
    total_products = products_repository.count_total_products(store_id)

    expired_items = products_repository.get_expired_products(store_id)

    expiring_soon_items = products_repository.get_expiring_soon_products(
        store_id, within_days=DASHBOARD_EXPIRY_SOON_DAYS
    )

    low_stock_items = products_repository.get_low_stock_products(store_id)

    return {
        "total_products": total_products,
        "expiring_soon_count": len(expiring_soon_items),
        "expiring_soon_items": expiring_soon_items,
        "expired_count": len(expired_items),
        "expired_items": expired_items,
        "low_stock_count": len(low_stock_items),
        "low_stock_items": low_stock_items,
    }
