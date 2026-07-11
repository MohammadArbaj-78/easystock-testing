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
"""

from datetime import date, datetime, timedelta

from core.database import get_connection
from core.exceptions import DatabaseError, ValidationError
from config.settings import DEFAULT_LOW_STOCK_THRESHOLD


def count_total_products(store_id: int) -> int:
    """Count all products belonging to a store.

    Args:
        store_id: The store to count products for.

    Returns:
        Total number of product rows for this store.
    """
    with get_connection() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS total FROM products WHERE store_id = ?",
            (store_id,),
        ).fetchone()
        return row["total"]


def get_expired_products(store_id: int) -> list:
    """Get all products whose expiry month/year is before the current month.

    Filters in Python (not SQL) because expiry_date is stored as a
    Month/Year string (e.g. "03/28", "Jun-2028") after the OCR migration.
    SQL string comparison against an ISO date produces wrong results for
    these values.
    """
    from utils.validators import parse_expiry_month_year
    from datetime import date
    today = date.today()
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT product_id, name, batch_number, expiry_date, quantity "
            "FROM products WHERE store_id = ?",
            (store_id,),
        ).fetchall()
    result = []
    for row in rows:
        try:
            m, y = parse_expiry_month_year(row["expiry_date"])
            if (y, m) < (today.year, today.month):
                result.append(dict(row))
        except ValueError:
            # Legacy ISO date (e.g. "2026-03-01") — fall back to ISO compare
            try:
                expiry_iso = date.fromisoformat(row["expiry_date"])
                if expiry_iso < today:
                    result.append(dict(row))
            except ValueError:
                pass
    result.sort(key=lambda r: r["expiry_date"])
    return result


def get_expiring_soon_products(store_id: int, within_days: int) -> list:
    """Get products expiring within within_days from today (not yet expired).

    Filters in Python for the same reason as get_expired_products.
    For MM/YY values, treats the expiry as the last day of that month
    so within_days comparison is conservative (includes the whole month).
    """
    from utils.validators import parse_expiry_month_year
    from datetime import date, timedelta
    import calendar
    today = date.today()
    cutoff = today + timedelta(days=within_days)
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT product_id, name, batch_number, expiry_date, quantity "
            "FROM products WHERE store_id = ?",
            (store_id,),
        ).fetchall()
    result = []
    for row in rows:
        try:
            m, y = parse_expiry_month_year(row["expiry_date"])
            # Not expired (current month or future)
            if (y, m) < (today.year, today.month):
                continue
            # Treat as the last day of the expiry month for within_days check
            last_day = calendar.monthrange(y, m)[1]
            expiry_end = date(y, m, last_day)
            if expiry_end <= cutoff:
                result.append(dict(row))
        except ValueError:
            # Legacy ISO date fall-back
            try:
                expiry_iso = date.fromisoformat(row["expiry_date"])
                if today <= expiry_iso <= cutoff:
                    result.append(dict(row))
            except ValueError:
                pass
    result.sort(key=lambda r: r["expiry_date"])
    return result


def get_low_stock_products(store_id: int) -> list:
    """Get all products whose quantity is at or below their minimum
    stock threshold.

    A product with no per-product threshold set (NULL in the database)
    falls back to DEFAULT_LOW_STOCK_THRESHOLD - this is implemented with
    SQLite's COALESCE so the fallback lives in one query rather than
    being applied inconsistently across different call sites.

    Args:
        store_id: The store to check.

    Returns:
        A list of dicts, one per low-stock product, each containing
        product_id, name, batch_number, quantity, and the effective
        threshold that was compared against.
    """
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                product_id,
                name,
                batch_number,
                quantity,
                COALESCE(minimum_stock_threshold, ?) AS effective_threshold
            FROM products
            WHERE store_id = ?
              AND quantity <= COALESCE(minimum_stock_threshold, ?)
            ORDER BY quantity ASC
            """,
            (DEFAULT_LOW_STOCK_THRESHOLD, store_id, DEFAULT_LOW_STOCK_THRESHOLD),
        ).fetchall()
        return [dict(row) for row in rows]


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


def get_product_by_id(store_id: int, product_id: int) -> dict:
    """Get a single product by ID, scoped to the requesting store.

    The store_id filter in the WHERE clause (not just on product_id) is
    what prevents one store from fetching another store's product by
    guessing or iterating IDs - this is the same ownership check used by
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
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM products WHERE store_id = ? AND product_id = ?",
            (store_id, product_id),
        ).fetchone()
        return dict(row) if row else None


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
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM products WHERE store_id = ? AND product_id = ?",
            (store_id, product_id),
        )
        if cursor.rowcount == 0:
            raise ValidationError(
                "Product not found, or you do not have permission to delete it."
            )
