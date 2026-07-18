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
"""

from core.database import get_connection
from config.settings import SALES_HISTORY_DISPLAY_LIMIT


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
