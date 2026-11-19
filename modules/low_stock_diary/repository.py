"""
Low Stock Diary repository - data access for the low_stock_diary table.

One row = one medicine the store owner noted down (finished / running low).
agency_id stays empty until the medicine is moved to an agency's list.
Every function takes store_id first. Dual backend like the other
repositories: Supabase (the table is created with database/low_stock_diary.sql)
or SQLite (the table is created here on first use).
"""

from config.settings import ACTIVE_DB_BACKEND


def list_entries(store_id: int) -> list:
    """Every diary row of the store, newest first:
    [{"diary_id", "name", "agency_id"}]."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _list_supabase(store_id)
    return _list_sqlite(store_id)


def add_entry(store_id: int, name: str, name_key: str) -> int:
    """Insert one medicine; returns its diary_id. A medicine that is already
    there (same name_key) makes the database raise - the service handles it."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _add_supabase(store_id, name, name_key)
    return _add_sqlite(store_id, name, name_key)


def delete_entries(store_id: int, diary_ids: list) -> None:
    """Delete these diary rows (of this store only)."""
    ids = [int(diary_id) for diary_id in diary_ids]
    if not ids:
        return
    if ACTIVE_DB_BACKEND == "supabase":
        _delete_supabase(store_id, ids)
    else:
        _delete_sqlite(store_id, ids)


def set_agency(store_id: int, diary_ids: list, agency_id) -> None:
    """Move these diary rows to an agency's "to order" list (agency_id), or
    back to the plain diary (agency_id None). Own store only."""
    ids = [int(diary_id) for diary_id in diary_ids]
    if not ids:
        return
    value = None if agency_id is None else int(agency_id)
    if ACTIVE_DB_BACKEND == "supabase":
        _table().update({"agency_id": value}).eq("store_id", store_id).in_("diary_id", ids).execute()
    else:
        _set_agency_sqlite(store_id, ids, value)


# --------------------------------------------------------------- Supabase

def _table():
    from core.supabase_client import get_supabase_client
    return get_supabase_client().table("low_stock_diary")


def _list_supabase(store_id: int) -> list:
    response = (
        _table().select("diary_id, name, agency_id")
        .eq("store_id", store_id).order("diary_id", desc=True).execute()
    )
    return response.data or []


def _add_supabase(store_id: int, name: str, name_key: str) -> int:
    response = _table().insert({"store_id": store_id, "name": name, "name_key": name_key}).execute()
    return response.data[0]["diary_id"]


def _delete_supabase(store_id: int, ids: list) -> None:
    _table().delete().eq("store_id", store_id).in_("diary_id", ids).execute()


# ----------------------------------------------------------------- SQLite

def _ensure_sqlite_table(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS low_stock_diary (
            diary_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id   INTEGER NOT NULL,
            name       TEXT NOT NULL,
            name_key   TEXT NOT NULL,
            agency_id  INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (store_id, name_key)
        )
        """
    )


def _list_sqlite(store_id: int) -> list:
    from core.database import get_connection
    with get_connection() as connection:
        _ensure_sqlite_table(connection)
        rows = connection.execute(
            "SELECT diary_id, name, agency_id FROM low_stock_diary WHERE store_id = ? ORDER BY diary_id DESC",
            (store_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _add_sqlite(store_id: int, name: str, name_key: str) -> int:
    from core.database import get_connection
    with get_connection() as connection:
        _ensure_sqlite_table(connection)
        cursor = connection.execute(
            "INSERT INTO low_stock_diary (store_id, name, name_key) VALUES (?, ?, ?)",
            (store_id, name, name_key),
        )
        return cursor.lastrowid


def _delete_sqlite(store_id: int, ids: list) -> None:
    from core.database import get_connection
    marks = ",".join("?" for _ in ids)
    with get_connection() as connection:
        _ensure_sqlite_table(connection)
        connection.execute(
            f"DELETE FROM low_stock_diary WHERE store_id = ? AND diary_id IN ({marks})",
            [store_id, *ids],
        )


def _set_agency_sqlite(store_id: int, ids: list, agency_id) -> None:
    from core.database import get_connection
    marks = ",".join("?" for _ in ids)
    with get_connection() as connection:
        _ensure_sqlite_table(connection)
        connection.execute(
            f"UPDATE low_stock_diary SET agency_id = ? WHERE store_id = ? AND diary_id IN ({marks})",
            [agency_id, store_id, *ids],
        )