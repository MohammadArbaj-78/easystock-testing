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
    matching logic needed here. Business rules layered on top, all
    belonging here (not in the repository, which has no concept of
    "sellable", and not in the UI, which must not contain business
    rules or SQL):
      - Out-of-stock products are never suggested (quantity must be > 0).
      - Exactly one result per distinct medicine name: when the same
        medicine has more than one in-stock lot (batch/expiry), only
        that medicine's FIFO-first lot (earliest expiry, the same
        order sell_product() already consumes lots in - see
        modules.products.service.get_lots_by_name_sorted_by_expiry, the
        single existing source of truth for this order, reused
        unmodified here) is shown. A newer batch of the same medicine
        never appears in search results while an older batch of it
        still has stock > 0, so a store owner can never accidentally
        pick a later-expiring batch out of search ahead of an
        earlier-expiring one that should sell first. This does not
        change which lot an actual sale consumes - sell_product()
        already applies this same FIFO order across every lot
        regardless of which specific batch row a search result pointed
        at; it only changes which single row search surfaces.
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
        expiry_date, and the other product fields), at most one per
        distinct medicine name, at most SALES_SEARCH_SUGGESTION_LIMIT
        of them.
    """
    from modules.products.service import get_lots_by_name_sorted_by_expiry

    products = products_repository.get_all_products(store_id, search_term)
    in_stock = [product for product in products if product["quantity"] > 0]

    seen_names = set()
    results = []
    for product in in_stock:
        name_key = product["name"].strip().lower()
        if name_key in seen_names:
            continue
        seen_names.add(name_key)

        fifo_lots = get_lots_by_name_sorted_by_expiry(store_id, product["name"])
        if fifo_lots:
            results.append(fifo_lots[0])

    return results[:SALES_SEARCH_SUGGESTION_LIMIT]


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


def get_sellable_stock(store_id: int, name: str) -> int:
    """Get the total sellable stock for a medicine name, summed across
    every in-stock lot (batch/expiry) of that name.

    A thin wrapper around products_service.get_lots_by_name_sorted_by_expiry
    (the same centralized lot lookup FIFO selling uses below), so the
    Sales UI can show/cap the quantity stepper against how much of this
    medicine can actually be sold in one transaction - not just the
    stock of whichever single batch row the store owner happened to
    click on.

    Args:
        store_id: The currently logged-in store's ID.
        name: Medicine name to total up.

    Returns:
        Sum of quantity across all in-stock lots of this name.
    """
    from modules.products.service import get_lots_by_name_sorted_by_expiry
    return sum(lot["quantity"] for lot in get_lots_by_name_sorted_by_expiry(store_id, name))


def sell_product(store_id: int, product_id: int, quantity: int) -> int:
    """Sell a quantity of a medicine, consuming stock First-Expiry-
    First-Out (FIFO) across every lot (batch/expiry) of that medicine's
    name - not only the specific batch row the store owner clicked on
    to start the sale (product_id is used only to look up which
    medicine name is being sold).

    Order of operations matters here and is deliberate, per lot
    consumed: stock is reduced first, and the sale is recorded only
    after that succeeds. If the reduction fails (not found, or not
    enough stock), nothing is recorded for that lot - there is no such
    thing as a sale of stock that was never actually reduced.

    A sale spanning more than one lot (the requested quantity exceeds
    the earliest-expiry lot's remaining stock) produces one
    sales_history row per lot consumed, each with that lot's own real
    batch_number and the quantity actually taken from it - the
    sales_history schema stores exactly one batch_number per row, so a
    single row could not otherwise represent stock pulled from more
    than one batch. modules.sales.repository.record_sale is reused
    unmodified for each of these rows.

    Args:
        store_id: The currently logged-in store's ID.
        product_id: The specific batch row the sale was started from -
            used only to resolve the medicine name being sold.
        quantity: Whole number of units to sell. Must be a positive
            integer - validated here independently of whatever UI
            widget constraints produced it, since this function must
            be safe to call from any future caller, not just the
            current UI.

    Returns:
        The sale_id of the last sales_history row written (the row for
        the final lot consumed).

    Raises:
        ValidationError: If quantity is not a positive whole number, if
            the product does not exist for this store, or if there is
            not enough total stock across all lots of this medicine to
            sell this quantity.
    """
    from modules.products.service import get_lots_by_name_sorted_by_expiry

    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise ValidationError("Quantity must be a whole number.")
    if quantity < 1:
        raise ValidationError("Quantity must be at least 1.")

    product = products_repository.get_product_by_id(store_id, product_id)
    if product is None:
        raise ValidationError("Product not found.")

    lots = get_lots_by_name_sorted_by_expiry(store_id, product["name"])
    total_available = sum(lot["quantity"] for lot in lots)
    if total_available < quantity:
        raise ValidationError(
            "Unable to sell this quantity - not enough stock available, "
            "or the product could not be found."
        )

    remaining_to_sell = quantity
    last_sale_id = None
    zeroed_product_ids = []
    zeroed_names = {}

    for lot in lots:
        if remaining_to_sell <= 0:
            break
        take = int(min(lot["quantity"], remaining_to_sell))

        # The real anti-oversell guard: an atomic conditional UPDATE,
        # not a separate "is quantity <= product['quantity']" check
        # here. A service-layer pre-check alone would be vulnerable to
        # a race between two near-simultaneous sales of the same stock -
        # the total_available check above is a fast pre-flight only,
        # this per-lot call is what actually enforces it.
        products_repository.reduce_stock(store_id, lot["product_id"], take)

        if take == lot["quantity"]:
            zeroed_product_ids.append(lot["product_id"])
            zeroed_names[lot["product_id"]] = lot["name"]

        last_sale_id = sales_repository.record_sale(
            store_id=store_id,
            product_id=lot["product_id"],
            medicine_name=lot["name"],
            batch_number=lot["batch_number"],
            sold_quantity=take,
        )

        remaining_to_sell -= take
    # Zero-quantity duplicate cleanup runs ONLY here, after every
    # reduce_stock()/record_sale() pair above has already completed -
    # deleting a lot before its own sale record is inserted would break
    # that insert with a foreign-key error (product_id no longer exists).
    for product_id in zeroed_product_ids:
        products_repository.cleanup_zero_quantity_duplicate(store_id, product_id)

    # cleanup_zero_quantity_duplicate() above only deletes a zeroed lot
    # when ANOTHER lot of the same name still has stock - it correctly
    # does nothing when this exact sale zeroed EVERY lot of a name at
    # once (no lot was left as a "stocked sibling"), so every one of
    # them survives instead of the usual single remaining zero-quantity
    # row. This only handles that specific case: names where 2+ lots
    # were zeroed by THIS sale. Re-checks each row still exists right
    # before deleting (the loop above may have already removed some of
    # them via an unrelated, still-stocked lot elsewhere) so this never
    # tries to delete an already-deleted row. Keeps exactly one
    # survivor per name, deletes the rest.
    zeroed_by_name = {}
    for product_id in zeroed_product_ids:
        name_key = zeroed_names[product_id].strip().lower()
        zeroed_by_name.setdefault(name_key, []).append(product_id)

    for product_ids in zeroed_by_name.values():
        if len(product_ids) < 2:
            continue
        survivors = [
            pid for pid in product_ids
            if products_repository.get_product_by_id(store_id, pid) is not None
        ]
        for product_id in survivors[1:]:
            products_repository.delete_product(store_id, product_id)

    return last_sale_id


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
