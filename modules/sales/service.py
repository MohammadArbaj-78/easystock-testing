"""
Sales business logic.

Owns validation and orchestration for selling a product - the rules for
what makes a sale valid and the order operations must happen in,
separate from how data is stored (modules.sales.repository,
modules.products.repository) or displayed (ui.py, not yet built).

This file contains no Streamlit imports and no raw SQL, matching every
other service in this codebase (see modules/products/service.py). It
reaches the products table only through modules.products.repository -
never modules.products.service - the same reuse pattern already
established by modules/dashboard/service.py and
modules/alerts/low_stock_service.py, so Sales stays decoupled from
Products' own business rules (e.g. future-expiry enforcement on add,
which has nothing to do with selling).
"""

from modules.products import repository as products_repository
from modules.sales import repository as sales_repository
from core.exceptions import ValidationError
from config.settings import SALES_SEARCH_SUGGESTION_LIMIT, SALES_FREQUENTLY_SOLD_LIMIT, SALES_FREQUENTLY_SOLD_CANDIDATE_LIMIT


def search_products(store_id: int, search_term: str) -> list:
    """Search sellable products, by name or batch number.

    A thin wrapper around products_repository.get_all_products, which
    already matches against both name and batch number - no new search
    matching logic needed here. Two business rules are layered on top,
    both belonging here (not in the repository, which has no concept
    of "sellable", and not in the UI, which must not contain business
    rules or SQL):
      - Out-of-stock products are never suggested (quantity must be > 0).
      - Results are capped at SALES_SEARCH_SUGGESTION_LIMIT - this is a
        lightweight autocomplete, not a full list; it should never
        return hundreds of results for the UI to render.

    Deciding whether to call this at all for an empty search term
    remains a UI-layer concern (Sales' UI shows a "start typing" prompt
    and Frequently Sold instead of listing every product), not a rule
    enforced here.

    Args:
        store_id: The currently logged-in store's ID.
        search_term: Text to filter by name or batch number.

    Returns:
        A list of in-stock product dicts (name, batch_number, quantity,
        expiry_date, and the other product fields), at most
        SALES_SEARCH_SUGGESTION_LIMIT of them.
    """
    products = products_repository.get_all_products(store_id, search_term)
    in_stock = [product for product in products if product["quantity"] > 0]
    return in_stock[:SALES_SEARCH_SUGGESTION_LIMIT]


def get_frequently_sold(store_id: int) -> list:
    """Get the top-selling, currently-in-stock products for this store.

    Combines sales_repository.get_top_sold_product_ids (a historical
    fact - which products have sold the most - with no notion of
    current stock) with products_repository.get_product_by_id (live
    data) to answer a question neither repository can answer alone:
    "what are this store's best sellers that it can actually still
    sell right now". A product that has sold well but is now out of
    stock, or has since been deleted, is silently skipped - never
    shown, matching the same "never suggest out-of-stock medicines"
    rule search_products enforces.

    Args:
        store_id: The currently logged-in store's ID.

    Returns:
        A list of in-stock product dicts, best-seller first, at most
        SALES_FREQUENTLY_SOLD_LIMIT of them. Empty list if this store
        has no sales history yet.
    """
    candidate_ids = sales_repository.get_top_sold_product_ids(
        store_id, SALES_FREQUENTLY_SOLD_CANDIDATE_LIMIT
    )

    results = []
    for product_id in candidate_ids:
        product = products_repository.get_product_by_id(store_id, product_id)
        if product is not None and product["quantity"] > 0:
            results.append(product)
        if len(results) >= SALES_FREQUENTLY_SOLD_LIMIT:
            break

    return results


def get_product(store_id: int, product_id: int) -> dict:
    """Get a single product's current, live data.

    A thin passthrough to products_repository.get_product_by_id, so the
    UI can re-check a previously-selected product's current stock
    (e.g. after selecting a search suggestion) without reaching into
    products_repository directly - the same layering rule every other
    UI file in this codebase already follows.

    Args:
        store_id: The currently logged-in store's ID.
        product_id: The product to look up.

    Returns:
        The product dict, or None if it does not exist for this store.
    """
    return products_repository.get_product_by_id(store_id, product_id)


def sell_product(store_id: int, product_id: int, quantity: int) -> int:
    """Sell a quantity of a product: reduce its stock and record the sale.

    Order of operations matters here and is deliberate: stock is
    reduced first, and the sale is recorded only after that succeeds.
    If the reduction fails (not found, or not enough stock), nothing is
    recorded - there is no such thing as a sale of stock that was never
    actually reduced. This also means the one accepted failure mode of
    this two-write sequence is a real sale whose history row failed to
    write (e.g. a transient DB error between the two calls) - never an
    inflated stock count or a phantom sale for stock that was never
    reduced.

    Args:
        store_id: The currently logged-in store's ID.
        product_id: The product being sold.
        quantity: Whole number of units to sell. Must be a positive
            integer - validated here independently of whatever UI
            widget constraints produced it, since this function must
            be safe to call from any future caller, not just the
            current UI.

    Returns:
        The newly created sale_id.

    Raises:
        ValidationError: If quantity is not a positive whole number, if
            the product does not exist for this store, or if there is
            not enough stock to sell this quantity (propagated from
            products_repository.reduce_stock's atomic check).
    """
    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise ValidationError("Quantity must be a whole number.")
    if quantity < 1:
        raise ValidationError("Quantity must be at least 1.")

    product = products_repository.get_product_by_id(store_id, product_id)
    if product is None:
        raise ValidationError("Product not found.")

    # The real anti-oversell guard: an atomic conditional UPDATE, not a
    # separate "is quantity <= product['quantity']" check here. A
    # service-layer pre-check alone would be vulnerable to a race
    # between two near-simultaneous sales of the same stock.
    products_repository.reduce_stock(store_id, product_id, quantity)

    return sales_repository.record_sale(
        store_id=store_id,
        product_id=product_id,
        medicine_name=product["name"],
        batch_number=product["batch_number"],
        sold_quantity=quantity,
    )


def get_sales_history(store_id: int) -> list:
    """Get the most recent sales for a store, newest first.

    A thin passthrough to sales_repository.get_sales_history - no
    filters, no pagination, matching the Sales History section's MVP
    scope (read-only, newest first, capped at
    config.settings.SALES_HISTORY_DISPLAY_LIMIT, no other parameters).

    Args:
        store_id: The currently logged-in store's ID.

    Returns:
        A list of sale dicts (sale_id, store_id, product_id,
        medicine_name, batch_number, sold_quantity, sold_at), newest
        first, limited to the most recent SALES_HISTORY_DISPLAY_LIMIT
        rows.
    """
    return sales_repository.get_sales_history(store_id)
