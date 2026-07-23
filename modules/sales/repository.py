"""
Sales repository - data access layer for the sales_history table only.

This file never reads or writes the products table - stock reduction
lives in modules.products.repository.reduce_stock, since that table
already has a single, shared data access point and this module reuses
it rather than duplicating product-table SQL (see modules/dashboard and
modules/alerts for the same reuse pattern).

sales_history is append-only by design: only an insert function
(record_sale) and read functions exist here. There is deliberately no
update or delete function for this table - a sale, once recorded, is a
permanent fact. Adding an update/delete path later would be a new,
visible function a reviewer would have to add on purpose, not something
that could slip in as a one-line change to something already here.

Every function takes store_id as its first required argument, sourced
by the calling service from core.session.get_current_store_id(), same
as every other repository in this codebase.

--- Phase 4 (Supabase migration): dual-backend, SQLite still active ---
This file now holds two implementations of every public function below,
exactly following the pattern established in modules/products/repository.py
during Phase 2/3: a SQLite implementation (the one actually used -
unchanged from before this phase) and a Supabase implementation (new,
inert). Every public function is a thin dispatcher on ACTIVE_DB_BACKEND,
imported from config/settings.py - the single, one-place switch shared
by every dual-backend repository (see that constant's own docstring and
AI_RULES.md's "Multi-Backend Repository Rules"). This file only ever
reads that constant; it does not define or override it. The Supabase
implementation uses the shared client from core.supabase_client
(imported lazily, so importing this module - or running the SQLite
path - never requires the `supabase`/`streamlit` packages to be
installed) and is not reachable or wired into anything unless
ACTIVE_DB_BACKEND is explicitly set to "supabase".
"""

from core.database import get_connection
from config.settings import ACTIVE_DB_BACKEND, SALES_HISTORY_DISPLAY_LIMIT


# =====================================================================
# Public API - dispatchers
#
# Every function here keeps the exact name, parameters, return value,
# and exceptions it had before this phase. Which implementation runs is
# an internal detail; callers (services) are unaffected regardless of
# which backend is active.
# =====================================================================


def record_sale(
    store_id: int,
    product_id: int,
    medicine_name: str,
    batch_number: str,
    sold_quantity: int,
) -> int:
    """Insert a new sale record. The only write this file performs.

    medicine_name and batch_number are snapshotted at the time of sale
    (passed in by the caller, not looked up here) so a sale record
    still reads correctly on its own even if the product is later
    renamed, re-batched, or deleted - the caller (sales/service.py) is
    responsible for capturing these values from the product at the
    moment of sale, before this function is called.

    Args:
        store_id: The store this sale belongs to.
        product_id: The product that was sold. Not a hard-cascading
            foreign key relationship enforced here - a sale record
            must remain meaningful even if the product row it refers
            to is later deleted.
        medicine_name: Snapshot of the product's name at sale time.
        batch_number: Snapshot of the product's batch number at sale time.
        sold_quantity: Whole number of units sold. Validation that this
            is positive and did not exceed available stock is the
            caller's (service.py) responsibility, enforced together
            with modules.products.repository.reduce_stock - this
            function trusts its input and focuses solely on persistence.

    Returns:
        The newly created sale_id.

    Raises:
        DatabaseError: If the insert fails (propagated from get_connection).
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _record_sale_supabase(
            store_id, product_id, medicine_name, batch_number, sold_quantity
        )
    return _record_sale_sqlite(
        store_id, product_id, medicine_name, batch_number, sold_quantity
    )


def get_top_sold_product_ids(store_id: int, limit: int) -> list:
    """Get product_ids ordered by total quantity sold, most-sold first.

    Pure aggregation over the existing sales_history table - no schema
    change, no new table. This function does not know about current
    stock (sales_history has no live stock column, and never will -
    quantities are historical snapshots); filtering out products that
    are now out of stock or deleted is the service layer's job, which
    is why this returns bare product_ids rather than deciding anything
    about which ones are still sellable.

    Args:
        store_id: The currently logged-in store's ID.
        limit: Maximum number of product_ids to return. The caller is
            expected to request more than it ultimately needs (some
            candidates may no longer be in stock) - this function has
            no opinion on that; it just aggregates and caps.

    Returns:
        A list of product_id values (ints), ordered by SUM(sold_quantity)
        descending.
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _get_top_sold_product_ids_supabase(store_id, limit)
    return _get_top_sold_product_ids_sqlite(store_id, limit)


def get_sales_history(store_id: int) -> list:
    """Get the most recent sales for a store, newest first.

    Capped at SALES_HISTORY_DISPLAY_LIMIT rows (config/settings.py) so
    this stays fast regardless of how many sales a store accumulates
    over time. No search term, date range, or offset parameters - the
    Sales History section has no filters and no pagination for the
    MVP; this function's bare signature is deliberately as thin as
    that requirement, so there's no unused plumbing inviting scope
    creep later.

    Args:
        store_id: The currently logged-in store's ID.

    Returns:
        A list of dicts (sale_id, store_id, product_id, medicine_name,
        batch_number, sold_quantity, sold_at), ordered by sold_at
        descending (most recent sale first), limited to the most
        recent SALES_HISTORY_DISPLAY_LIMIT rows.
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _get_sales_history_supabase(store_id)
    return _get_sales_history_sqlite(store_id)


# =====================================================================
# Shared, backend-agnostic aggregation logic
#
# PostgREST has no GROUP BY/SUM query-builder equivalent for
# get_top_sold_product_ids, so the Supabase implementation fetches raw
# rows and aggregates them in Python. Factored out here (rather than
# written inline in the Supabase function) purely so a future backend
# needing the same aggregation isn't tempted to re-derive it - this is
# data-shaping local to the repository layer, not business logic that
# belongs in the service layer. The SQLite implementation is unaffected
# and keeps doing this aggregation in SQL, exactly as before this phase.
# =====================================================================


def _aggregate_top_sold_product_ids(rows: list, limit: int) -> list:
    """Given raw rows (dicts) with product_id and sold_quantity, return
    product_ids ordered by total sold_quantity descending, capped at
    limit - the same result shape SQLite's SUM/GROUP BY/ORDER BY/LIMIT
    query produces.
    """
    totals = {}
    for raw_row in rows:
        row = dict(raw_row)
        pid = row["product_id"]
        totals[pid] = totals.get(pid, 0) + row["sold_quantity"]
    ordered = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    return [pid for pid, _ in ordered[:limit]]


# =====================================================================
# SQLite implementations (active backend)
# =====================================================================


def _record_sale_sqlite(
    store_id: int,
    product_id: int,
    medicine_name: str,
    batch_number: str,
    sold_quantity: int,
) -> int:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO sales_history (
                store_id, product_id, medicine_name, batch_number, sold_quantity
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (store_id, product_id, medicine_name, batch_number, sold_quantity),
        )
        return cursor.lastrowid


def _get_top_sold_product_ids_sqlite(store_id: int, limit: int) -> list:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT product_id, SUM(sold_quantity) AS total_sold
            FROM sales_history
            WHERE store_id = ?
            GROUP BY product_id
            ORDER BY total_sold DESC
            LIMIT ?
            """,
            (store_id, limit),
        ).fetchall()
        return [row["product_id"] for row in rows]


def _get_sales_history_sqlite(store_id: int) -> list:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT sale_id, store_id, product_id, medicine_name,
                   batch_number, sold_quantity, sold_at
            FROM sales_history
            WHERE store_id = ?
            ORDER BY sold_at DESC
            LIMIT ?
            """,
            (store_id, SALES_HISTORY_DISPLAY_LIMIT),
        ).fetchall()
        return [dict(row) for row in rows]


# =====================================================================
# Supabase implementations (Phase 4 - prepared, not yet active)
#
# Not imported, called, or exercised by any code path outside this file
# while ACTIVE_DB_BACKEND == "sqlite". Every function below is scoped by
# store_id exactly like its SQLite counterpart - no query here can read
# or write another store's row. sales_history has no update/delete
# function on either backend, matching this file's append-only design.
# =====================================================================


def _supabase_sales_history_table():
    """Return the Supabase 'sales_history' table query builder.

    Lazily imports core.supabase_client (which itself lazily creates
    the client) so this module stays importable, and its SQLite path
    fully usable, without the `supabase`/`streamlit` packages installed.
    This import only ever executes if ACTIVE_DB_BACKEND is "supabase".
    """
    from core.supabase_client import get_supabase_client
    return get_supabase_client().table("sales_history")


def _record_sale_supabase(
    store_id: int,
    product_id: int,
    medicine_name: str,
    batch_number: str,
    sold_quantity: int,
) -> int:
    # sold_at is intentionally omitted from the payload, exactly as the
    # SQLite implementation never passes it either - SQLite's schema
    # defaults it to datetime('now'); the future Supabase table is
    # expected to default its equivalent column the same way (a
    # Supabase-side schema concern, not Python code, out of scope here -
    # same kind of documented dependency as reduce_stock's RPC function
    # in modules/products/repository.py).
    payload = {
        "store_id": store_id,
        "product_id": product_id,
        "medicine_name": medicine_name,
        "batch_number": batch_number,
        "sold_quantity": sold_quantity,
    }
    response = _supabase_sales_history_table().insert(payload).execute()
    return response.data[0]["sale_id"]


def _get_top_sold_product_ids_supabase(store_id: int, limit: int) -> list:
    response = (
        _supabase_sales_history_table()
        .select("product_id, sold_quantity")
        .eq("store_id", store_id)
        .execute()
    )
    return _aggregate_top_sold_product_ids(response.data, limit)


def _get_sales_history_supabase(store_id: int) -> list:
    response = (
        _supabase_sales_history_table()
        .select("sale_id, store_id, product_id, medicine_name, batch_number, sold_quantity, sold_at")
        .eq("store_id", store_id)
        .order("sold_at", desc=True)
        .limit(SALES_HISTORY_DISPLAY_LIMIT)
        .execute()
    )
    return [dict(row) for row in response.data]
