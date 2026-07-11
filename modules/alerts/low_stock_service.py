"""
Low Stock Alerts business logic.

Deliberately thin: the repository already does the heavy lifting
(querying products whose quantity <= their effective threshold, with
COALESCE fallback to the global default). This service adds only what
the repository shouldn't own: search filtering and the severity tier
that drives the UI's color coding.

No new SQL is written here. modules.products.repository.get_low_stock_products
is the single data source for this module - the same function Dashboard
already calls, so the Dashboard count and this page's list are always
in agreement.
"""

from modules.products import repository as products_repository
from config.settings import DEFAULT_LOW_STOCK_THRESHOLD

# Severity tiers for low-stock urgency, based on how far below the
# effective threshold a product's quantity has fallen.
# Defined as a config-like structure here (not scattered across the UI)
# so the thresholds and colors for each tier live in one place.
#
# Tier rules (applied in order, first match wins):
#   CRITICAL  — quantity is 0 (completely out of stock)
#   WARNING   — quantity is between 1 and 50% of the effective threshold
#   LOW       — quantity is above 50% of threshold but still <= threshold
#
# These boundaries were chosen to give actionable gradations: a store
# owner needs to know the difference between "completely out" and
# "getting low but not urgent yet." If a future version exposes a
# configurable severity boundary, this is where it would live.
SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_LOW = "low"

SEVERITY_DISPLAY = {
    SEVERITY_CRITICAL: {"label": "Out of Stock", "color": "#D32F2F", "icon": "🔴"},
    SEVERITY_WARNING:  {"label": "Very Low Stock", "color": "#F57C00", "icon": "🟠"},
    SEVERITY_LOW:      {"label": "Low Stock", "color": "#FBC02D", "icon": "🟡"},
}

ALL_SEVERITIES = [SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_LOW]


def _get_severity(quantity: int, effective_threshold: int) -> str:
    """Assign a severity tier to a low-stock product.

    Args:
        quantity: The product's current stock level.
        effective_threshold: The threshold it was compared against
            (already resolved from per-product or global default by
            the repository query).

    Returns:
        One of the SEVERITY_* constants.
    """
    if quantity == 0:
        return SEVERITY_CRITICAL
    if effective_threshold > 0 and quantity <= effective_threshold * 0.5:
        return SEVERITY_WARNING
    return SEVERITY_LOW


def get_low_stock_alerts(store_id: int, search_term: str = None) -> dict:
    """Fetch low-stock products for a store, grouped by severity tier,
    optionally filtered by a name/batch search term.

    Reuses products_repository.get_low_stock_products - the same
    function Dashboard uses for its Low Stock count, so this page's
    list and Dashboard's count are guaranteed to agree.

    Args:
        store_id: The currently logged-in store's ID.
        search_term: Optional text, matched case-insensitively as a
            substring against name or batch_number.

    Returns:
        A dict keyed by SEVERITY_* constants, each value a list of
        product dicts (name, batch_number, quantity, effective_threshold)
        sorted by quantity ascending within each tier (most urgent
        first), so the store owner sees the emptiest shelves at the top.
    """
    all_low_stock = products_repository.get_low_stock_products(store_id)

    if search_term and search_term.strip():
        term = search_term.strip().lower()
        all_low_stock = [
            p for p in all_low_stock
            if term in p["name"].lower() or term in p["batch_number"].lower()
        ]

    buckets = {severity: [] for severity in ALL_SEVERITIES}
    for product in all_low_stock:
        severity = _get_severity(product["quantity"], product["effective_threshold"])
        buckets[severity].append(product)

    # Already ordered by quantity ASC from the repository (emptiest
    # first), which is the correct display order within each tier.
    return buckets


def get_low_stock_counts(store_id: int) -> dict:
    """Get just the count per severity tier for the filter dropdown's
    labels, without fetching full product details.

    Args:
        store_id: The currently logged-in store's ID.

    Returns:
        A dict keyed by SEVERITY_* constants, values are int counts.
        Also includes a "total" key for the summary header.
    """
    buckets = get_low_stock_alerts(store_id)
    counts = {severity: len(products) for severity, products in buckets.items()}
    counts["total"] = sum(counts.values())
    return counts
