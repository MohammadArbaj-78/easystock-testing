"""
Quick Setup repository - search the shared medicine master reference
list, and create/update each store's "Quick Setup placeholder" row in
products.

medicine_master is a SHARED, read-only reference table (not scoped by
store_id) - the same ~2.5 lakh Indian medicines for every store.

A "placeholder" row in products is how Quick Setup represents "I have
some of this medicine, but I don't know its exact batch/expiry/MRP/rate
yet" - it is the ONE product row for (store_id, name) that has an EMPTY
batch_number. Saving the same medicine again from Quick Setup always
updates (never duplicates) this one placeholder row. A real invoice
scan always creates a row with a REAL batch_number, so a placeholder
row and a real-batch row for the same medicine can coexist side by
side without conflict.
"""

from core.database import get_connection
from config.settings import ACTIVE_DB_BACKEND


def search_master_medicines(search_term: str, limit: int = 20) -> list:
    """Search the shared medicine master list by name.

    Returns:
        List of {"name", "manufacturer_name", "composition", "mrp"},
        or [] if search_term is blank.
    """
    term = (search_term or "").strip()
    if not term:
        return []
    if ACTIVE_DB_BACKEND == "supabase":
        return _search_master_medicines_supabase(term, limit)
    return _search_master_medicines_sqlite(term, limit)

def browse_master_medicines(limit: int) -> list:
    """First `limit` medicines from the master list, name order - lets
    the owner browse without typing a search term first, same
    Load-more pattern as Products' own list."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _browse_master_medicines_supabase(limit)
    return _browse_master_medicines_sqlite(limit)


def _browse_master_medicines_sqlite(limit: int) -> list:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT name, manufacturer_name, short_composition1, short_composition2, price
            FROM medicine_master ORDER BY name ASC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_format_master_row(dict(row)) for row in rows]


def _browse_master_medicines_supabase(limit: int) -> list:
    response = (
        _medicine_master_table()
        .select("name, manufacturer_name, short_composition1, short_composition2, price")
        .order("name")
        .limit(limit)
        .execute()
    )
    return [_format_master_row(row) for row in (response.data or [])]

def get_placeholder_quantity(store_id: int, name: str) -> float:
    """Quantity already saved for this medicine's Quick Setup
    placeholder row (0 if none exists yet)."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _get_placeholder_quantity_supabase(store_id, name)
    return _get_placeholder_quantity_sqlite(store_id, name)


def save_placeholder_quantities(store_id: int, name_to_quantity: dict) -> int:
    """Create or update each medicine's Quick Setup placeholder row to
    the given quantity. SETS (never adds). Only entries with
    quantity > 0 are saved. An existing REAL-batch row for the same
    name is never touched.

    Returns:
        How many medicines were saved.
    """
    to_save = {name: qty for name, qty in name_to_quantity.items() if qty and qty > 0}
    if not to_save:
        return 0
    if ACTIVE_DB_BACKEND == "supabase":
        return _save_placeholder_quantities_supabase(store_id, to_save)
    return _save_placeholder_quantities_sqlite(store_id, to_save)


# ---------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------

def _search_master_medicines_sqlite(term: str, limit: int) -> list:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT name, manufacturer_name, short_composition1, short_composition2, price
            FROM medicine_master
            WHERE name LIKE ? COLLATE NOCASE
            ORDER BY name ASC
            LIMIT ?
            """,
            (f"%{term}%", limit),
        ).fetchall()
    return [_format_master_row(dict(row)) for row in rows]


def _get_placeholder_quantity_sqlite(store_id: int, name: str) -> float:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT quantity FROM products
            WHERE store_id = ? AND name = ? COLLATE NOCASE
                  AND (batch_number IS NULL OR batch_number = '')
            """,
            (store_id, name),
        ).fetchone()
    return float(row["quantity"]) if row else 0.0


def _save_placeholder_quantities_sqlite(store_id: int, name_to_quantity: dict) -> int:
    saved = 0
    with get_connection() as connection:
        for name, quantity in name_to_quantity.items():
            existing = connection.execute(
                """
                SELECT product_id FROM products
                WHERE store_id = ? AND name = ? COLLATE NOCASE
                      AND (batch_number IS NULL OR batch_number = '')
                """,
                (store_id, name),
            ).fetchone()
            if existing:
                connection.execute(
                    "UPDATE products SET quantity = ? WHERE product_id = ?",
                    (quantity, existing["product_id"]),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO products
                        (store_id, name, batch_number, expiry_date, quantity, mrp, rate)
                    VALUES (?, ?, '', '', ?, '', '')
                    """,
                    (store_id, name, quantity),
                )
            saved += 1
    return saved


def _format_master_row(row: dict) -> dict:
    composition = " + ".join(
        part for part in (row.get("short_composition1"), row.get("short_composition2")) if part
    )
    return {
        "name": row.get("name") or "",
        "manufacturer_name": row.get("manufacturer_name") or "",
        "composition": composition,
        "mrp": row.get("price"),
    }


# ---------------------------------------------------------------------
# Supabase - NOT tested live (same caveat as agencies module). Follows
# the exact same dispatcher pattern.
# ---------------------------------------------------------------------

def _medicine_master_table():
    from core.supabase_client import get_supabase_client
    return get_supabase_client().table("medicine_master")


def _products_table():
    from core.supabase_client import get_supabase_client
    return get_supabase_client().table("products")


def _search_master_medicines_supabase(term: str, limit: int) -> list:
    response = (
        _medicine_master_table()
        .select("name, manufacturer_name, short_composition1, short_composition2, price")
        .ilike("name", f"%{term}%")
        .order("name")
        .limit(limit)
        .execute()
    )
    return [_format_master_row(row) for row in (response.data or [])]


def _get_placeholder_quantity_supabase(store_id: int, name: str) -> float:
    response = (
        _products_table()
        .select("quantity")
        .eq("store_id", store_id)
        .eq("name", name)
        .or_("batch_number.is.null,batch_number.eq.")
        .execute()
    )
    rows = response.data or []
    return float(rows[0]["quantity"]) if rows else 0.0


def _save_placeholder_quantities_supabase(store_id: int, name_to_quantity: dict) -> int:
    saved = 0
    for name, quantity in name_to_quantity.items():
        existing = (
            _products_table()
            .select("product_id")
            .eq("store_id", store_id)
            .eq("name", name)
            .or_("batch_number.is.null,batch_number.eq.")
            .execute()
        ).data or []
        if existing:
            _products_table().update({"quantity": quantity}).eq(
                "product_id", existing[0]["product_id"]
            ).execute()
        else:
            _products_table().insert({
                "store_id": store_id,
                "name": name,
                "batch_number": "",
                "expiry_date": "",
                "quantity": quantity,
                "mrp": "",
                "rate": "",
            }).execute()
        saved += 1
    return saved