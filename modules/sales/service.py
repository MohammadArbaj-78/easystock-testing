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
    term = (search_term or "").strip().lower()

    # Speed: group the rows we ALREADY fetched by medicine name, so the
    # FIFO lot of most results can be found in memory instead of one
    # extra database call per medicine.
    rows_by_name = {}
    for product in products:
        rows_by_name.setdefault(product["name"].strip().lower(), []).append(product)

    seen_names = set()
    results = []
    for product in products:
        if product["quantity"] <= 0:
            continue
        name_key = product["name"].strip().lower()
        if name_key in seen_names:
            continue
        seen_names.add(name_key)

        if term and term.isascii() and name_key.isascii() and term in name_key:
            # Search term is inside this medicine's NAME, so the database
            # matched every lot of this name - all are already in
            # `products`. Same rule as get_lots_by_name_sorted_by_expiry.
            fifo_lots = sorted(
                (row for row in rows_by_name[name_key] if row["quantity"] > 0),
                key=lambda row: row["product_id"],
            )
        else:
            # Matched by batch number only - ask the database for all lots.
            fifo_lots = get_lots_by_name_sorted_by_expiry(store_id, product["name"])

        if fifo_lots:
            results.append(fifo_lots[0])
        if len(results) >= SALES_SEARCH_SUGGESTION_LIMIT:
            break

    return results
    
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
    if not candidate_ids:
        return []

    # Speed: fetch this store's products ONCE and resolve every candidate
    # in memory, instead of two database calls per candidate.
    all_products = products_repository.get_all_products(store_id)
    products_by_id = {row["product_id"]: row for row in all_products}

    # In-stock lots per medicine name, oldest arrival first (same FIFO
    # rule as get_lots_by_name_sorted_by_expiry).
    lots_by_name = {}
    for row in all_products:
        if row["quantity"] > 0:
            lots_by_name.setdefault(row["name"].strip().lower(), []).append(row)
    for lots in lots_by_name.values():
        lots.sort(key=lambda row: row["product_id"])

    seen_names = set()
    results = []
    for product_id in candidate_ids:
        product = products_by_id.get(product_id)
        if product is None or product["quantity"] <= 0:
            continue

        name_key = product["name"].strip().lower()
        if name_key in seen_names:
            continue
        seen_names.add(name_key)

        fifo_lots = lots_by_name.get(name_key)
        if fifo_lots:
            results.append(fifo_lots[0])

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


# ---------------------------------------------------------------------------
# Flexible search and auto-setup from the master medicine list
#
# Nothing above this line was changed. The functions below add:
#   - search_store_products: the same store search as search_products, plus
#     a fallback that understands words typed in any order ("telsar h tab"
#     finds "Telsar-H Tablet") - used only when search_products found
#     nothing, so existing results and their order never change.
#   - search_master_medicines: the fallback shown ONLY when the store has
#     no match at all - ranked, with a single-salt suggestion next to each
#     combination medicine.
#   - save_master_medicine / save_new_medicine: add a medicine to the
#     store's stock with a starting quantity. Both reuse Quick Setup's
#     existing save, so no new SQL is written.
# ---------------------------------------------------------------------------

# A one-letter search would match thousands of master rows, so the master
# fallback only starts at this many characters.
MASTER_SEARCH_MIN_CHARACTERS = 2

# How many master rows each of the three lookups may fetch before ranking.
_MASTER_PREFIX_FETCH_LIMIT = 60
_MASTER_CONTAINS_FETCH_LIMIT = 120
_MASTER_COMBINATION_FETCH_LIMIT = 40

# If a search matches combination medicines, at least this many are shown
# even when single-salt names fill the first page.
_MIN_COMBINATIONS_SHOWN = 2


def search_store_products(store_id: int, search_term: str) -> list:
    """Search this store's in-stock medicines.

    Exactly search_products() first. Only if that finds nothing, a second
    pass matches the typed words in ANY order and ignores punctuation and
    Tab/Tablet-style spelling differences (core.name_matching), so a
    medicine the store really has is not missed - which would otherwise
    wrongly send the owner to the master list.

    Same result shape and rules as search_products: in-stock only, one row
    per medicine name (its FIFO-first lot), at most
    SALES_SEARCH_SUGGESTION_LIMIT rows.
    """
    from core import name_matching

    results = search_products(store_id, search_term)
    if results:
        return results

    term = (search_term or "").strip()
    words = name_matching.search_words(term)
    if len(term) < MASTER_SEARCH_MIN_CHARACTERS or not words:
        return []

    # Narrow the database read by the longest typed word; the careful
    # word-by-word comparison then runs in memory on that small set.
    narrowing_word = max((word.replace("%", "") for word in words), key=len)
    if not narrowing_word:
        return []
    products = products_repository.get_all_products(store_id, narrowing_word)

    lots_by_name = {}
    for product in products:
        lots_by_name.setdefault(product["name"].strip().lower(), []).append(product)

    ranked = []
    for rows in lots_by_name.values():
        in_stock = sorted(
            (row for row in rows if row["quantity"] > 0),
            key=lambda row: row["product_id"],   # FIFO: earliest arrival first
        )
        if not in_stock:
            continue
        tier = name_matching.match_tier(in_stock[0]["name"], words)
        if tier is None:
            continue
        ranked.append((tier, in_stock[0]["name"].lower(), in_stock[0]))

    ranked.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in ranked[:SALES_SEARCH_SUGGESTION_LIMIT]]


def search_master_medicines(search_term: str) -> list:
    """Search the shared medicine master list, for the Sales fallback
    shown ONLY when search_store_products found nothing in this store.
    (The caller decides when to call it; this function only looks at the
    master list.)

    Ranking: names that start with what was typed come first, then names
    where every typed word starts a word of the name, then the rest; within
    each, single-salt medicines before combinations. Each combination
    medicine that the typed words point at gets a single-salt suggestion
    placed right before it ("StayHappi Ambroxol Syrup" before
    "StayHappi Ambroxol+Guaifenesin+Terbutaline ... Syrup").

    Returns:
        A list of {"name", "manufacturer_name", "composition", "mrp"}
        dicts, one per distinct name, [] if the term is shorter than
        MASTER_SEARCH_MIN_CHARACTERS.
    """
    from core import name_matching
    from modules.quick_setup import service as quick_setup_service

    term = (search_term or "").strip()
    if len(term) < MASTER_SEARCH_MIN_CHARACTERS:
        return []
    words = name_matching.search_words(term)
    if not words:
        return []

    try:
        rows = (
            quick_setup_service.search_medicines_all_words(
                words, True, _MASTER_PREFIX_FETCH_LIMIT
            )
            + quick_setup_service.search_medicines_all_words(
                words, False, _MASTER_CONTAINS_FETCH_LIMIT
            )
            # Combination names start with a brand (StayHappi, Genericart,
            # ...), so alphabetically they come late and could be cut off
            # by the limit above; fetch them separately.
            + quick_setup_service.search_medicines_all_words(
                words + ["+"], False, _MASTER_COMBINATION_FETCH_LIMIT
            )
        )
    except Exception:
        # Safety net: if the word-based lookup fails for any reason, fall
        # back to the plain one-piece-of-text search Quick Setup has always
        # used, so the owner still gets suggestions.
        rows = quick_setup_service.search_medicines(
            term, limit=SALES_SEARCH_SUGGESTION_LIMIT * 3
        )

    unique = {}
    for row in rows:
        name = name_matching.clean_spaces(row.get("name"))
        key = name_matching.normalized_name(name)
        if name and key and key not in unique:
            unique[key] = dict(row, name=name)

    def sort_key(row):
        tier = name_matching.match_tier(row["name"], words)
        return (
            3 if tier is None else tier,
            name_matching.is_combination(row["name"]),
            row["name"].lower(),
        )

    ranked = sorted(unique.values(), key=sort_key)
    shown = ranked[:SALES_SEARCH_SUGGESTION_LIMIT]

    combinations_shown = sum(1 for row in shown if name_matching.is_combination(row["name"]))
    if combinations_shown < _MIN_COMBINATIONS_SHOWN:
        extra = [
            row for row in ranked[SALES_SEARCH_SUGGESTION_LIMIT:]
            if name_matching.is_combination(row["name"])
        ]
        shown = shown + extra[: _MIN_COMBINATIONS_SHOWN - combinations_shown]

    results = []
    already_listed = set(unique)
    for row in shown:
        if name_matching.is_combination(row["name"]):
            for single in name_matching.split_combination(row["name"], words):
                single_key = name_matching.normalized_name(single["name"])
                if single_key in already_listed:
                    continue          # a real master row of that name exists
                already_listed.add(single_key)
                results.append({
                    "name": single["name"],
                    "manufacturer_name": "",
                    "composition": single["salt"],
                    "mrp": None,
                })
        results.append(row)
    return results


def is_valid_new_medicine_name(name: str):
    """Whether text typed in the Sales search box is acceptable as the
    name of a brand-new medicine (3-100 characters, at least one letter).
    Returns (True, cleaned_name) or (False, ""). Lets the UI ask the
    service instead of importing core.name_matching itself."""
    from core import name_matching

    return name_matching.is_valid_new_medicine_name(name)


def _save_new_stock_row(store_id: int, clean_name: str, quantity: int) -> None:
    """Shared by save_master_medicine and save_new_medicine: validate the
    quantity, refuse a medicine that is already in stock, then save it the
    way Quick Setup saves a medicine - one product row with just a name and
    quantity (blank batch/expiry/MRP). When a real invoice for it is
    scanned later, the existing placeholder rule in
    modules.products.service fills those in.
    """
    from core import name_matching
    from modules.quick_setup import service as quick_setup_service

    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise ValidationError("Quantity must be a whole number.")
    if quantity < 1:
        raise ValidationError("Quantity must be at least 1.")

    wanted = name_matching.normalized_name(clean_name)
    already_in_stock = any(
        name_matching.normalized_name(product["name"]) == wanted
        for product in search_store_products(store_id, clean_name)
    )
    if already_in_stock:
        raise ValidationError(
            "This medicine is already in your system. "
            "Please search for it again and use Sell."
        )

    quick_setup_service.save_quantities(store_id, {clean_name: quantity})


def save_master_medicine(store_id: int, name: str, quantity: int) -> None:
    """Add a medicine suggested from the master list (or a single-salt
    name made from a combination) to this store's stock.

    Args:
        store_id: The currently logged-in store's ID.
        name: The suggested medicine name.
        quantity: Whole number of units, at least 1.

    Raises:
        ValidationError: Blank name, quantity not a whole number >= 1, or
            the medicine is already in stock (it should be sold, not
            saved again - that would create a duplicate row).
    """
    from core import name_matching

    clean_name = name_matching.clean_spaces(name)
    if not clean_name:
        raise ValidationError("Medicine name is required.")
    _save_new_stock_row(store_id, clean_name, quantity)


def save_new_medicine(store_id: int, name: str, quantity: int) -> None:
    """Add a medicine the owner typed in full because it was found neither
    in the store nor in the master list.

    Same as save_master_medicine, plus a check on the typed name (3-100
    characters, at least one letter) - see
    core.name_matching.is_valid_new_medicine_name.

    Raises:
        ValidationError: As save_master_medicine, or the typed name is not
            acceptable.
    """
    from core import name_matching

    is_valid, clean_name = name_matching.is_valid_new_medicine_name(name)
    if not is_valid:
        raise ValidationError(
            "Please type the full medicine name (3 to 100 characters, with letters)."
        )
    _save_new_stock_row(store_id, clean_name, quantity)