"""Store settings repository - small per-store switches (one row per store).

Table: store_app_settings. Same dual-backend pattern as the other
repositories: SQLite by default, Supabase when ACTIVE_DB_BACKEND is
"supabase".
"""

from datetime import datetime, timezone

from core.database import get_connection
from config.settings import ACTIVE_DB_BACKEND


def get_save_real_qty(store_id: int):
    """True / False as saved for this store, or None if never saved."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _get_save_real_qty_supabase(store_id)
    return _get_save_real_qty_sqlite(store_id)


def set_save_real_qty(store_id: int, value: bool) -> None:
    """Save the switch for this store (replaces any earlier value)."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _set_save_real_qty_supabase(store_id, value)
    return _set_save_real_qty_sqlite(store_id, value)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get_save_real_qty_sqlite(store_id: int):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT save_real_qty FROM store_app_settings WHERE store_id = ?",
            (store_id,),
        ).fetchone()
    if not row or row["save_real_qty"] is None:
        return None
    return bool(row["save_real_qty"])


def _set_save_real_qty_sqlite(store_id: int, value: bool) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO store_app_settings (store_id, save_real_qty, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(store_id) DO UPDATE SET
                save_real_qty = excluded.save_real_qty,
                updated_at = excluded.updated_at
            """,
            (store_id, 1 if value else 0, _now()),
        )


def _settings_table():
    from core.supabase_client import get_supabase_client
    return get_supabase_client().table("store_app_settings")


def _get_save_real_qty_supabase(store_id: int):
    rows = (
        _settings_table().select("save_real_qty").eq("store_id", store_id).limit(1).execute()
    ).data or []
    if not rows or rows[0].get("save_real_qty") is None:
        return None
    return bool(rows[0]["save_real_qty"])


def _set_save_real_qty_supabase(store_id: int, value: bool) -> None:
    _settings_table().upsert(
        {"store_id": store_id, "save_real_qty": bool(value), "updated_at": _now()},
        on_conflict="store_id",
    ).execute()