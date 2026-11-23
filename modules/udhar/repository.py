"""
Udhar Khata repository - data access for udhar_customers and udhar_entries.

kind "gave"  = udhar diya (the customer owes more),
kind "got"   = paise mile (the customer owes less).
The balance is never stored: it is (sum of gave) - (sum of got), read from the
view udhar_customer_balances (Supabase) or worked out in the query (SQLite).
Every function takes store_id first, and every read / write is limited to it.
Dual backend like the other repositories; the SQLite tables are created here
on first use, the Supabase ones with database/udhar_khata.sql.
"""

from config.settings import ACTIVE_DB_BACKEND


def list_customers(store_id: int) -> list:
    """Every customer of the store with the balance:
    [{"customer_id", "name", "mobile", "balance", "last_entry_date"}]."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _list_customers_supabase(store_id)
    return _list_customers_sqlite(store_id)


def add_customer(store_id: int, name: str, mobile: str) -> int:
    """Insert a customer; returns customer_id. The same mobile twice makes
    the database raise (unique) - the service handles it."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _add_customer_supabase(store_id, name, mobile)
    return _add_customer_sqlite(store_id, name, mobile)


def get_customer(store_id: int, customer_id: int):
    """One customer row (with balance) of this store, or None."""
    for row in list_customers(store_id):
        if row["customer_id"] == customer_id:
            return row
    return None


def delete_customer(store_id: int, customer_id: int) -> None:
    """Delete a customer (and, by the table rules, their entries)."""
    if ACTIVE_DB_BACKEND == "supabase":
        _table("udhar_customers").delete().eq("store_id", store_id).eq("customer_id", customer_id).execute()
    else:
        _delete_customer_sqlite(store_id, customer_id)


def add_entry(store_id: int, customer_id: int, kind: str, amount: float, note, entry_date: str) -> int:
    """Insert one entry; returns entry_id."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _add_entry_supabase(store_id, customer_id, kind, amount, note, entry_date)
    return _add_entry_sqlite(store_id, customer_id, kind, amount, note, entry_date)


def list_entries(store_id: int, customer_id: int, limit: int = 300) -> list:
    """The customer's latest entries, newest first:
    [{"entry_id", "kind", "amount", "note", "entry_date"}]."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _list_entries_supabase(store_id, customer_id, limit)
    return _list_entries_sqlite(store_id, customer_id, limit)


def list_all_entries(store_id: int) -> list:
    """Every entry of every customer of the store, oldest first (used only by
    the PDF record): [{"entry_id", "customer_id", "kind", "amount", "note", "entry_date"}]."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _list_all_entries_supabase(store_id)
    return _list_all_entries_sqlite(store_id)


def delete_entry(store_id: int, entry_id: int) -> None:
    if ACTIVE_DB_BACKEND == "supabase":
        _table("udhar_entries").delete().eq("store_id", store_id).eq("entry_id", entry_id).execute()
    else:
        _delete_entry_sqlite(store_id, entry_id)


# --------------------------------------------------------------- Supabase

def _table(name: str):
    from core.supabase_client import get_supabase_client
    return get_supabase_client().table(name)


def _list_customers_supabase(store_id: int) -> list:
    rows = (
        _table("udhar_customer_balances")
        .select("customer_id, name, mobile, balance, last_entry_date")
        .eq("store_id", store_id).limit(5000).execute()
    ).data or []
    return [dict(row, balance=round(float(row.get("balance") or 0), 2)) for row in rows]


def _list_all_entries_supabase(store_id: int) -> list:
    rows, start, page = [], 0, 1000                  # the API gives at most 1000 rows at a time
    while True:
        chunk = (
            _table("udhar_entries")
            .select("entry_id, customer_id, kind, amount, note, entry_date")
            .eq("store_id", store_id).order("entry_id")
            .range(start, start + page - 1).execute()
        ).data or []
        rows += chunk
        if len(chunk) < page:
            break
        start += page
    return [dict(row, amount=float(row["amount"])) for row in rows]


def _add_customer_supabase(store_id: int, name: str, mobile: str) -> int:
    response = _table("udhar_customers").insert({"store_id": store_id, "name": name, "mobile": mobile}).execute()
    return response.data[0]["customer_id"]


def _add_entry_supabase(store_id, customer_id, kind, amount, note, entry_date) -> int:
    payload = {
        "store_id": store_id, "customer_id": customer_id, "kind": kind,
        "amount": amount, "note": note, "entry_date": entry_date,
    }
    response = _table("udhar_entries").insert(payload).execute()
    return response.data[0]["entry_id"]


def _list_entries_supabase(store_id: int, customer_id: int, limit: int) -> list:
    rows = (
        _table("udhar_entries")
        .select("entry_id, kind, amount, note, entry_date")
        .eq("store_id", store_id).eq("customer_id", customer_id)
        .order("entry_date", desc=True).order("entry_id", desc=True)
        .limit(limit).execute()
    ).data or []
    return [dict(row, amount=float(row["amount"])) for row in rows]


# ----------------------------------------------------------------- SQLite

def _ensure_sqlite_tables(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS udhar_customers (
            customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id    INTEGER NOT NULL,
            name        TEXT NOT NULL,
            mobile      TEXT NOT NULL,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (store_id, mobile)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS udhar_entries (
            entry_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id    INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            kind        TEXT NOT NULL CHECK (kind IN ('gave', 'got')),
            amount      REAL NOT NULL CHECK (amount > 0),
            note        TEXT,
            entry_date  TEXT NOT NULL,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _list_customers_sqlite(store_id: int) -> list:
    from core.database import get_connection
    with get_connection() as connection:
        _ensure_sqlite_tables(connection)
        rows = connection.execute(
            """
            SELECT c.customer_id, c.name, c.mobile,
                   COALESCE(SUM(CASE WHEN e.kind = 'gave' THEN e.amount
                                     WHEN e.kind = 'got' THEN -e.amount END), 0) AS balance,
                   MAX(e.entry_date) AS last_entry_date
            FROM udhar_customers c
            LEFT JOIN udhar_entries e ON e.customer_id = c.customer_id
            WHERE c.store_id = ?
            GROUP BY c.customer_id
            """,
            (store_id,),
        ).fetchall()
    return [dict(row, balance=round(float(row["balance"] or 0), 2)) for row in rows]


def _add_customer_sqlite(store_id: int, name: str, mobile: str) -> int:
    from core.database import get_connection
    with get_connection() as connection:
        _ensure_sqlite_tables(connection)
        cursor = connection.execute(
            "INSERT INTO udhar_customers (store_id, name, mobile) VALUES (?, ?, ?)",
            (store_id, name, mobile),
        )
        return cursor.lastrowid


def _add_entry_sqlite(store_id, customer_id, kind, amount, note, entry_date) -> int:
    from core.database import get_connection
    with get_connection() as connection:
        _ensure_sqlite_tables(connection)
        cursor = connection.execute(
            "INSERT INTO udhar_entries (store_id, customer_id, kind, amount, note, entry_date) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (store_id, customer_id, kind, amount, note, entry_date),
        )
        return cursor.lastrowid


def _list_entries_sqlite(store_id: int, customer_id: int, limit: int) -> list:
    from core.database import get_connection
    with get_connection() as connection:
        _ensure_sqlite_tables(connection)
        rows = connection.execute(
            "SELECT entry_id, kind, amount, note, entry_date FROM udhar_entries "
            "WHERE store_id = ? AND customer_id = ? ORDER BY entry_date DESC, entry_id DESC LIMIT ?",
            (store_id, customer_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def _list_all_entries_sqlite(store_id: int) -> list:
    from core.database import get_connection
    with get_connection() as connection:
        _ensure_sqlite_tables(connection)
        rows = connection.execute(
            "SELECT entry_id, customer_id, kind, amount, note, entry_date FROM udhar_entries "
            "WHERE store_id = ? ORDER BY entry_id",
            (store_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _delete_entry_sqlite(store_id: int, entry_id: int) -> None:
    from core.database import get_connection
    with get_connection() as connection:
        _ensure_sqlite_tables(connection)
        connection.execute("DELETE FROM udhar_entries WHERE store_id = ? AND entry_id = ?", (store_id, entry_id))


def _delete_customer_sqlite(store_id: int, customer_id: int) -> None:
    from core.database import get_connection
    with get_connection() as connection:
        _ensure_sqlite_tables(connection)
        connection.execute("DELETE FROM udhar_entries WHERE store_id = ? AND customer_id = ?", (store_id, customer_id))
        connection.execute("DELETE FROM udhar_customers WHERE store_id = ? AND customer_id = ?", (store_id, customer_id))