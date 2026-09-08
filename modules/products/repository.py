"""
Products repository - data access layer for the products table.

Originally built minimal (read-only) to support Dashboard. Now extended
with full CRUD for Product Management - this is the single, shared data
access point for the products table; Dashboard and Product Management
both call into this same file, which is exactly why Dashboard reflects
new products automatically with no Dashboard code changes required.

Every method takes store_id as its first required argument, sourced by
the calling service from core.session.get_current_store_id(). There is
no method here that can read, write, or delete across stores - that is
enforced by every method's signature and, for update/delete, by an
explicit ownership check before the write executes.

--- Phase 2 (Supabase migration): dual-backend, SQLite still active ---
This file holds two implementations of every public function below: a
SQLite implementation (the one actually used - unchanged from before
that phase) and a Supabase implementation (new as of Phase 2, inert).
Every public function is a thin dispatcher on ACTIVE_DB_BACKEND. The
Supabase implementations use the shared client from core.supabase_client
(imported lazily, so importing this module - or running the SQLite path -
never requires the `supabase`/`streamlit` packages to be installed) and
are not reachable or wired into anything unless ACTIVE_DB_BACKEND is
explicitly set to "supabase" and has been verified against a real
Supabase project.

--- Phase 3 (Supabase migration): single-place backend selection ---
ACTIVE_DB_BACKEND is imported from config/settings.py, not defined here.
That is the one and only place the active backend is chosen (via the
ACTIVE_DB_BACKEND environment variable, defaulting to and failing safe
to "sqlite") - this file, and any future dual-backend repository, only
ever reads it. See AI_RULES.md's "Multi-Backend Repository Rules" for
the conventions this dual-backend shape follows.
"""

from datetime import date, datetime, timedelta

from core.database import get_connection
from core.exceptions import DatabaseError, ValidationError
from config.settings import ACTIVE_DB_BACKEND, DEFAULT_LOW_STOCK_THRESHOLD

# Phase 3: backend selection is no longer defined in this file. It is
# imported above from config/settings.py - the single, one-place switch
# shared by every dual-backend repository - so this file only ever
# reads it, never redefines or overrides it. See config/settings.py's
# "Database backend selection" section and AI_RULES.md's "Multi-Backend
# Repository Rules" for why the value must live in exactly one place.


# =====================================================================
# Public API - dispatchers
#
# Every function here keeps the exact name, parameters, return value,
# and exceptions it had before this phase. Which implementation runs is
# an internal detail; callers (services, other repositories) are
# unaffected by this phase regardless of which backend is active.
# =====================================================================


def count_total_products(store_id: int) -> int:
    """Count all products belonging to a store.

    Args:
        store_id: The store to count products for.

    Returns:
        Total number of product rows for this store.
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _count_total_products_supabase(store_id)
    return _count_total_products_sqlite(store_id)


def get_expired_products(store_id: int) -> list:
    """Get all products whose expiry month/year is before the current month.

    Filters in Python (not SQL) because expiry_date is stored as a
    Month/Year string (e.g. "03/28", "Jun-2028") after the OCR migration.
    SQL string comparison against an ISO date produces wrong results for
    these values.
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _get_expired_products_supabase(store_id)
    return _get_expired_products_sqlite(store_id)


def get_expiring_soon_products(store_id: int, within_days: int) -> list:
    """Get products expiring within within_days from today (not yet expired).

    Filters in Python for the same reason as get_expired_products.
    For MM/YY values, treats the expiry as the last day of that month
    so within_days comparison is conservative (includes the whole month).
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _get_expiring_soon_products_supabase(store_id, within_days)
    return _get_expiring_soon_products_sqlite(store_id, within_days)


def get_low_stock_products(store_id: int, global_minimum: int = None) -> list:
    """Get all products whose quantity is at or below their minimum
    stock threshold.

    A product with no per-product threshold set (NULL in the database)
    falls back to global_minimum (Requirement 5) - or, if that is not
    given, to the existing DEFAULT_LOW_STOCK_THRESHOLD, exactly as
    before this feature. Every existing caller (e.g.
    modules/dashboard/service.py) that does not pass global_minimum is
    completely unaffected by this change.

    Args:
        store_id: The store to check.
        global_minimum: Optional override for the store-wide default
            threshold, used only by the Low Stock page's dropdown
            (modules/alerts/low_stock_service.py). A product's own
            non-NULL minimum_stock_threshold always wins over this,
            unchanged.

    Returns:
        A list of dicts, one per low-stock product, each containing
        product_id, name, batch_number, quantity, and the effective
        threshold that was compared against.
    """
    effective_default = global_minimum if global_minimum is not None else DEFAULT_LOW_STOCK_THRESHOLD
    if ACTIVE_DB_BACKEND == "supabase":
        return _get_low_stock_products_supabase(store_id, effective_default)
    return _get_low_stock_products_sqlite(store_id, effective_default)


def get_all_products(store_id: int, search_term: str = None) -> list:
    """Get all products for a store, optionally filtered by a search
    term matched against medicine name or batch number.

    Args:
        store_id: The store whose products to list.
        search_term: Optional text to filter by. Matched case-insensitively
            as a substring against both name and batch_number, since a
            store owner searching might remember only part of a name or
            only the batch number printed on a strip.

    Returns:
        A list of dicts, one per matching product, containing every
        column in the products table, ordered by name for predictable,
        scannable listing.
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _get_all_products_supabase(store_id, search_term)
    return _get_all_products_sqlite(store_id, search_term)


def get_product_by_id(store_id: int, product_id: int) -> dict:
    """Get a single product by ID, scoped to the requesting store.

    The store_id filter (not just product_id) is what prevents one
    store from fetching another store's product by guessing or
    iterating IDs - this is the same ownership check used by
    update_product and delete_product below.

    Args:
        store_id: The store that must own this product.
        product_id: The product's primary key.

    Returns:
        A dict of the product's columns, or None if no product with that
        ID exists for this store (either it doesn't exist at all, or it
        belongs to a different store - the caller cannot distinguish
        these two cases, which is intentional).
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _get_product_by_id_supabase(store_id, product_id)
    return _get_product_by_id_sqlite(store_id, product_id)


def create_product(store_id: int, product_data: dict) -> int:
    """Insert a new product row for a store.

    Args:
        store_id: The store this product belongs to.
        product_data: Dict with keys matching product_schema field keys:
            name, batch_number, expiry_date (ISO string), quantity,
            minimum_stock_threshold (optional, may be None), mrp,
            rate (optional), gst_percent (optional),
            purchase_date (optional ISO string).
            Validation of these values is the caller's (service.py)
            responsibility - this function trusts its input and focuses
            solely on persistence.

    Returns:
        The newly created product_id.

    Raises:
        DatabaseError: If the insert fails.
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _create_product_supabase(store_id, product_data)
    return _create_product_sqlite(store_id, product_data)


def update_product(store_id: int, product_id: int, product_data: dict) -> None:
    """Update an existing product row, scoped to the requesting store.

    Args:
        store_id: The store that must own this product.
        product_id: The product to update.
        product_data: Dict with the same keys as create_product.

    Raises:
        ValidationError: If no product with this ID exists for this
            store - raised here (not silently doing nothing) so the
            service layer and UI can tell the difference between "saved"
            and "nothing happened because the ID didn't match this
            store", which matters both for honest user feedback and as
            a tripwire if a store_id/product_id mismatch ever occurs.
        DatabaseError: If the update fails for any other reason.
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _update_product_supabase(store_id, product_id, product_data)
    return _update_product_sqlite(store_id, product_id, product_data)


def delete_product(store_id: int, product_id: int) -> None:
    """Delete a product, scoped to the requesting store.

    Args:
        store_id: The store that must own this product.
        product_id: The product to delete.

    Raises:
        ValidationError: If no product with this ID exists for this
            store. See update_product's docstring for why this raises
            rather than silently no-op-ing.
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _delete_product_supabase(store_id, product_id)
    return _delete_product_sqlite(store_id, product_id)


def reduce_stock(store_id: int, product_id: int, quantity: int) -> None:
    """Atomically decrement a product's stock by quantity (used by Sales).

    The availability check and the write happen in the same atomic
    operation, not as a separate read-then-write. This is what actually
    prevents overselling under concurrent access: two near-simultaneous
    calls attempting to sell the last unit cannot both succeed. A
    service-layer "check stock, then write" pattern alone would be
    vulnerable to exactly that race; this function is the real guard,
    not a convenience wrapper around one.

    Also enforces store ownership the same way update_product/
    delete_product do, so this cannot reduce another store's stock even
    given a guessed or stale product_id.

    Args:
        store_id: The store that must own this product.
        product_id: The product whose stock is being reduced.
        quantity: Whole number of units to subtract. Must be positive -
            validating that is the caller's (service.py) responsibility;
            this function trusts its input's type but not its
            availability, which is exactly what the atomic check covers.

    Raises:
        ValidationError: If no product with this ID exists for this
            store, or if the product's current quantity is less than
            the requested quantity (insufficient stock). Both causes
            produce the same result and are deliberately not
            distinguished here, matching the same combined-cause
            pattern update_product/delete_product already use for
            "not found or not yours" - the caller cannot tell which
            case occurred, which is acceptable since the resulting
            user-facing message ("not enough stock, or item not found")
            is correct either way.
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _reduce_stock_supabase(store_id, product_id, quantity)
    return _reduce_stock_sqlite(store_id, product_id, quantity)


# =====================================================================
# Shared, backend-agnostic filtering logic
#
# Both the SQLite and Supabase implementations of the expiry-bucket and
# low-stock queries need the exact same Python-side filtering (SQLite,
# because expiry_date can't be compared with SQL date operators;
# Supabase, for the same reason plus because PostgREST has no
# equivalent of SQLite's COALESCE-in-WHERE for the threshold fallback).
# Defined once here so neither implementation can drift from the other -
# this is data-shaping local to the repository layer, not business logic
# that belongs in the service layer.
# =====================================================================


def _filter_expired_rows(rows: list) -> list:
    """Given raw product rows (dicts) with expiry_date, name, etc.,
    return only those already expired, sorted by expiry_date.
    """
    from utils.validators import parse_expiry_month_year
    today = date.today()
    result = []
    for raw_row in rows:
        row = dict(raw_row)
        try:
            m, y = parse_expiry_month_year(row["expiry_date"])
            if (y, m) < (today.year, today.month):
                result.append(row)
        except ValueError:
            # Legacy ISO date (e.g. "2026-03-01") - fall back to ISO compare
            try:
                expiry_iso = date.fromisoformat(row["expiry_date"])
                if expiry_iso < today:
                    result.append(row)
            except ValueError:
                pass
    result.sort(key=lambda r: r["expiry_date"])
    return result


def _filter_expiring_soon_rows(rows: list, within_days: int) -> list:
    """Given raw product rows (dicts), return those expiring within
    within_days from today (not yet expired), sorted by expiry_date.
    """
    from utils.validators import parse_expiry_month_year
    import calendar
    today = date.today()
    cutoff = today + timedelta(days=within_days)
    result = []
    for raw_row in rows:
        row = dict(raw_row)
        try:
            m, y = parse_expiry_month_year(row["expiry_date"])
            # Not expired (current month or future)
            if (y, m) < (today.year, today.month):
                continue
            # Treat as the last day of the expiry month for within_days check
            last_day = calendar.monthrange(y, m)[1]
            expiry_end = date(y, m, last_day)
            if expiry_end <= cutoff:
                result.append(row)
        except ValueError:
            # Legacy ISO date fall-back
            try:
                expiry_iso = date.fromisoformat(row["expiry_date"])
                if today <= expiry_iso <= cutoff:
                    result.append(row)
            except ValueError:
                pass
    result.sort(key=lambda r: r["expiry_date"])
    return result


def _filter_low_stock_rows(rows: list, effective_default: int = None) -> list:
    """Given raw product rows (dicts) with quantity and
    minimum_stock_threshold, return only those at or below their
    effective threshold (per-product if set, else effective_default -
    or, if that is not given, DEFAULT_LOW_STOCK_THRESHOLD, exactly as
    before this feature), sorted by quantity ascending.
    """
    if effective_default is None:
        effective_default = DEFAULT_LOW_STOCK_THRESHOLD
    result = []
    for raw_row in rows:
        row = dict(raw_row)
        effective_threshold = row.get("minimum_stock_threshold")
        if effective_threshold is None:
            effective_threshold = effective_default
        if row["quantity"] <= effective_threshold:
            result.append({
                "product_id": row["product_id"],
                "name": row["name"],
                "batch_number": row["batch_number"],
                "quantity": row["quantity"],
                "mrp": row.get("mrp"),
                "rate": row.get("rate"),
                "effective_threshold": effective_threshold,
            })
    result.sort(key=lambda r: r["quantity"])
    return result


# =====================================================================
# SQLite implementations (active backend)
# =====================================================================


def _count_total_products_sqlite(store_id: int) -> int:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS total FROM products WHERE store_id = ?",
            (store_id,),
        ).fetchone()
        return row["total"]


def _get_expired_products_sqlite(store_id: int) -> list:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT product_id, name, batch_number, expiry_date, quantity, mrp, rate "
            "FROM products WHERE store_id = ?",
            (store_id,),
        ).fetchall()
    return _filter_expired_rows(rows)


def _get_expiring_soon_products_sqlite(store_id: int, within_days: int) -> list:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT product_id, name, batch_number, expiry_date, quantity, mrp, rate "
            "FROM products WHERE store_id = ?",
            (store_id,),
        ).fetchall()
    return _filter_expiring_soon_rows(rows, within_days)


def _get_low_stock_products_sqlite(store_id: int, effective_default: int) -> list:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                product_id,
                name,
                batch_number,
                quantity,
                mrp,
                rate,
                COALESCE(minimum_stock_threshold, ?) AS effective_threshold
            FROM products
            WHERE store_id = ?
              AND quantity <= COALESCE(minimum_stock_threshold, ?)
            ORDER BY quantity ASC
            """,
            (effective_default, store_id, effective_default),
        ).fetchall()
        return [dict(row) for row in rows]


def _get_all_products_sqlite(store_id: int, search_term: str = None) -> list:
    with get_connection() as connection:
        if search_term and search_term.strip():
            pattern = f"%{search_term.strip()}%"
            rows = connection.execute(
                """
                SELECT * FROM products
                WHERE store_id = ?
                  AND (name LIKE ? COLLATE NOCASE
                       OR batch_number LIKE ? COLLATE NOCASE)
                ORDER BY name ASC
                """,
                (store_id, pattern, pattern),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM products WHERE store_id = ? ORDER BY name ASC",
                (store_id,),
            ).fetchall()
        return [dict(row) for row in rows]


def _get_product_by_id_sqlite(store_id: int, product_id: int) -> dict:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM products WHERE store_id = ? AND product_id = ?",
            (store_id, product_id),
        ).fetchone()
        return dict(row) if row else None


def _create_product_sqlite(store_id: int, product_data: dict) -> int:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO products (
                store_id, name, batch_number, expiry_date, quantity,
                minimum_stock_threshold, mrp, rate, gst_percent, purchase_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                store_id,
                product_data["name"],
                product_data["batch_number"],
                product_data["expiry_date"],
                product_data["quantity"],
                product_data.get("minimum_stock_threshold"),
                product_data["mrp"],
                product_data.get("rate"),
                product_data.get("gst_percent"),
                product_data.get("purchase_date"),
            ),
        )
        return cursor.lastrowid


def _update_product_sqlite(store_id: int, product_id: int, product_data: dict) -> None:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE products SET
                name = ?,
                batch_number = ?,
                expiry_date = ?,
                quantity = ?,
                minimum_stock_threshold = ?,
                mrp = ?,
                rate = ?,
                gst_percent = ?,
                purchase_date = ?,
                updated_at = ?
            WHERE store_id = ? AND product_id = ?
            """,
            (
                product_data["name"],
                product_data["batch_number"],
                product_data["expiry_date"],
                product_data["quantity"],
                product_data.get("minimum_stock_threshold"),
                product_data["mrp"],
                product_data.get("rate"),
                product_data.get("gst_percent"),
                product_data.get("purchase_date"),
                datetime.now().isoformat(timespec="seconds"),
                store_id,
                product_id,
            ),
        )
        if cursor.rowcount == 0:
            raise ValidationError(
                "Product not found, or you do not have permission to edit it."
            )


def _delete_product_sqlite(store_id: int, product_id: int) -> None:
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM products WHERE store_id = ? AND product_id = ?",
            (store_id, product_id),
        )
        if cursor.rowcount == 0:
            raise ValidationError(
                "Product not found, or you do not have permission to delete it."
            )


def _reduce_stock_sqlite(store_id: int, product_id: int, quantity: int) -> None:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE products
            SET quantity = quantity - ?, updated_at = ?
            WHERE store_id = ? AND product_id = ? AND quantity >= ?
            """,
            (
                quantity,
                datetime.now().isoformat(timespec="seconds"),
                store_id,
                product_id,
                quantity,
            ),
        )
        if cursor.rowcount == 0:
            raise ValidationError(
                "Unable to sell this quantity - not enough stock available, "
                "or the product could not be found."
            )

# =====================================================================
# Supabase implementations (Phase 2 - prepared, not yet active)
#
# Not imported, called, or exercised by any code path outside this file
# while ACTIVE_DB_BACKEND == "sqlite". Every function below is scoped by
# store_id exactly like its SQLite counterpart - no query here can read,
# write, or delete another store's row.
# =====================================================================


def _supabase_products_table():
    """Return the Supabase 'products' table query builder.

    Lazily imports core.supabase_client (which itself lazily creates
    the client - see that module's docstring) so this module stays
    importable, and its SQLite path fully usable, without the
    `supabase`/`streamlit` packages installed. This import only ever
    executes if ACTIVE_DB_BACKEND is switched to "supabase".
    """
    from core.supabase_client import get_supabase_client
    return get_supabase_client().table("products")


def _count_total_products_supabase(store_id: int) -> int:
    response = (
        _supabase_products_table()
        .select("product_id", count="exact")
        .eq("store_id", store_id)
        .execute()
    )
    return response.count or 0


def _get_expired_products_supabase(store_id: int) -> list:
    response = (
        _supabase_products_table()
        .select("product_id, name, batch_number, expiry_date, quantity, mrp, rate")
        .eq("store_id", store_id)
        .execute()
    )
    return _filter_expired_rows(response.data)


def _get_expiring_soon_products_supabase(store_id: int, within_days: int) -> list:
    response = (
        _supabase_products_table()
        .select("product_id, name, batch_number, expiry_date, quantity, mrp, rate")
        .eq("store_id", store_id)
        .execute()
    )
    return _filter_expiring_soon_rows(response.data, within_days)


def _get_low_stock_products_supabase(store_id: int, effective_default: int) -> list:
    # PostgREST has no COALESCE-in-WHERE equivalent for the effective
    # threshold fallback, so - like the expiry queries above - the
    # comparison happens in Python via the shared _filter_low_stock_rows
    # helper, against every row for this store rather than a
    # pre-filtered SQL result set.
    response = (
        _supabase_products_table()
        .select("product_id, name, batch_number, quantity, mrp, rate, minimum_stock_threshold")
        .eq("store_id", store_id)
        .execute()
    )
    return _filter_low_stock_rows(response.data, effective_default)


def _get_all_products_supabase(store_id: int, search_term: str = None) -> list:
    query = _supabase_products_table().select("*").eq("store_id", store_id)
    if search_term and search_term.strip():
        # PostgREST's or() filter syntax uses commas to separate
        # conditions and treats them specially inside the ilike
        # pattern's own value; escape any comma in the search term so
        # a store owner searching for e.g. a comma-containing batch
        # label can't produce a malformed filter.
        term = search_term.strip().replace(",", "\\,")
        pattern = f"%{term}%"
        query = query.or_(f"name.ilike.{pattern},batch_number.ilike.{pattern}")
    response = query.order("name", desc=False).execute()
    return [dict(row) for row in response.data]


def _get_product_by_id_supabase(store_id: int, product_id: int) -> dict:
    response = (
        _supabase_products_table()
        .select("*")
        .eq("store_id", store_id)
        .eq("product_id", product_id)
        .execute()
    )
    rows = response.data
    return dict(rows[0]) if rows else None


def _create_product_supabase(store_id: int, product_data: dict) -> int:
    payload = {
        "store_id": store_id,
        "name": product_data["name"],
        "batch_number": product_data["batch_number"],
        "expiry_date": product_data["expiry_date"],
        "quantity": product_data["quantity"],
        "minimum_stock_threshold": product_data.get("minimum_stock_threshold"),
        "mrp": product_data["mrp"],
        "rate": product_data.get("rate"),
        "gst_percent": product_data.get("gst_percent"),
        "purchase_date": product_data.get("purchase_date"),
    }
    response = _supabase_products_table().insert(payload).execute()
    return response.data[0]["product_id"]


def _update_product_supabase(store_id: int, product_id: int, product_data: dict) -> None:
    payload = {
        "name": product_data["name"],
        "batch_number": product_data["batch_number"],
        "expiry_date": product_data["expiry_date"],
        "quantity": product_data["quantity"],
        "minimum_stock_threshold": product_data.get("minimum_stock_threshold"),
        "mrp": product_data["mrp"],
        "rate": product_data.get("rate"),
        "gst_percent": product_data.get("gst_percent"),
        "purchase_date": product_data.get("purchase_date"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    response = (
        _supabase_products_table()
        .update(payload)
        .eq("store_id", store_id)
        .eq("product_id", product_id)
        .execute()
    )
    if not response.data:
        raise ValidationError(
            "Product not found, or you do not have permission to edit it."
        )


def _delete_product_supabase(store_id: int, product_id: int) -> None:
    response = (
        _supabase_products_table()
        .delete()
        .eq("store_id", store_id)
        .eq("product_id", product_id)
        .execute()
    )
    if not response.data:
        raise ValidationError(
            "Product not found, or you do not have permission to delete it."
        )


def _reduce_stock_supabase(store_id: int, product_id: int, quantity: int) -> None:
    """Atomic decrement via a Postgres RPC function, not a client-side
    conditional update.

    PostgREST's update endpoint only accepts literal values in its
    request body - it cannot express "quantity = quantity - ? WHERE
    quantity >= ?" (an update whose value and whose guard condition both
    depend on the row's current value) in a single call the way the
    SQLite implementation's one UPDATE statement does. Reading the
    current quantity first and writing it back from Python would
    reintroduce exactly the read-then-write race this function exists
    to prevent (see reduce_stock's docstring). The correct equivalent is
    a single atomic operation on the database side: a Postgres function
    (expected name: reduce_product_stock(p_store_id, p_product_id,
    p_quantity), returning the number of rows updated - 0 or 1) that
    performs the same guarded UPDATE that core/database.py's SQLite
    schema uses today. See AI_RULES.md's Multi-Backend Repository Rules.

    That function is a Supabase-side schema addition (a migration, not
    Python code) and does not exist yet - out of scope for this
    repository-only phase. This path is not reachable while
    ACTIVE_DB_BACKEND == "sqlite", and must not be switched to "supabase"
    until the RPC function has been created and this path verified
    against a real Supabase project.
    """
    from core.supabase_client import get_supabase_client
    response = get_supabase_client().rpc(
        "reduce_product_stock",
        {"p_store_id": store_id, "p_product_id": product_id, "p_quantity": quantity},
    ).execute()
    rows_affected = response.data
    if not rows_affected:
        raise ValidationError(
            "Unable to sell this quantity - not enough stock available, "
            "or the product could not be found."
        )
    

def cleanup_zero_quantity_duplicate(store_id: int, product_id: int) -> None:
    """After a sale has fully recorded, delete a lot that this sale
    reduced to 0 IF another lot of the same medicine name still has
    stock. Called only after sales_history's insert for this exact
    product_id has already completed - deleting any earlier (inside
    reduce_stock) would break that insert with a foreign-key error,
    since sales_history.product_id references this same row.
    """
    if ACTIVE_DB_BACKEND == "supabase":
        _cleanup_zero_quantity_duplicate_supabase(store_id, product_id)
    else:
        _cleanup_zero_quantity_duplicate_sqlite(store_id, product_id)


def _cleanup_zero_quantity_duplicate_sqlite(store_id: int, product_id: int) -> None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT name, quantity FROM products WHERE store_id = ? AND product_id = ?",
            (store_id, product_id),
        ).fetchone()
        if row is not None and row["quantity"] == 0:
            sibling = connection.execute(
                """
                SELECT 1 FROM products
                WHERE store_id = ? AND name = ? COLLATE NOCASE
                  AND product_id != ? AND quantity > 0
                LIMIT 1
                """,
                (store_id, row["name"], product_id),
            ).fetchone()
            if sibling is not None:
                connection.execute(
                    "DELETE FROM products WHERE store_id = ? AND product_id = ?",
                    (store_id, product_id),
                )


def _cleanup_zero_quantity_duplicate_supabase(store_id: int, product_id: int) -> None:
    current = _get_product_by_id_supabase(store_id, product_id)
    if current is not None and current["quantity"] == 0:
        sibling_response = (
            _supabase_products_table()
            .select("product_id")
            .eq("store_id", store_id)
            .ilike("name", current["name"])
            .neq("product_id", product_id)
            .gt("quantity", 0)
            .limit(1)
            .execute()
        )
        if sibling_response.data:
            _delete_product_supabase(store_id, product_id)