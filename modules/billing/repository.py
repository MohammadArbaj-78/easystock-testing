"""Billing repository - the store's bill seal / sign image (one row per store).

Same dual-backend pattern as the other repositories: SQLite by default,
Supabase when ACTIVE_DB_BACKEND is "supabase".
"""

from datetime import datetime, timezone

from core.database import get_connection
from config.settings import ACTIVE_DB_BACKEND


def get_seal_sign(store_id: int):
    """The store's saved seal/sign as a data-URI string, or None."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _get_seal_sign_supabase(store_id)
    return _get_seal_sign_sqlite(store_id)


def get_bill_settings(store_id: int) -> dict:
    """{"seal_sign_image": data-URI or None, "dl_number": text or None}."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _get_bill_settings_supabase(store_id)
    return _get_bill_settings_sqlite(store_id)


def save_dl_number(store_id: int, dl_number: str) -> None:
    """Save the store's Drug Licence number (empty text clears it)."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _save_dl_number_supabase(store_id, dl_number)
    return _save_dl_number_sqlite(store_id, dl_number)


def save_seal_sign(store_id: int, data_uri: str) -> None:
    """Save the store's seal/sign. A new one replaces the old one."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _save_seal_sign_supabase(store_id, data_uri)
    return _save_seal_sign_sqlite(store_id, data_uri)


def _get_seal_sign_sqlite(store_id: int):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT seal_sign_image FROM store_bill_settings WHERE store_id = ?",
            (store_id,),
        ).fetchone()
    return (row["seal_sign_image"] or None) if row else None


def _save_seal_sign_sqlite(store_id: int, data_uri: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO store_bill_settings (store_id, seal_sign_image, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(store_id) DO UPDATE SET
                seal_sign_image = excluded.seal_sign_image,
                updated_at = excluded.updated_at
            """,
            (store_id, data_uri, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


def _get_bill_settings_sqlite(store_id: int) -> dict:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT seal_sign_image, dl_number FROM store_bill_settings WHERE store_id = ?",
            (store_id,),
        ).fetchone()
    if not row:
        return {"seal_sign_image": None, "dl_number": None}
    return {"seal_sign_image": row["seal_sign_image"] or None, "dl_number": row["dl_number"] or None}


def _save_dl_number_sqlite(store_id: int, dl_number: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO store_bill_settings (store_id, dl_number, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(store_id) DO UPDATE SET
                dl_number = excluded.dl_number,
                updated_at = excluded.updated_at
            """,
            (store_id, dl_number, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


def _settings_table():
    from core.supabase_client import get_supabase_client
    return get_supabase_client().table("store_bill_settings")


def _get_seal_sign_supabase(store_id: int):
    rows = (
        _settings_table().select("seal_sign_image").eq("store_id", store_id).limit(1).execute()
    ).data or []
    return (rows[0].get("seal_sign_image") or None) if rows else None


def _save_seal_sign_supabase(store_id: int, data_uri: str) -> None:
    _settings_table().upsert(
        {
            "store_id": store_id,
            "seal_sign_image": data_uri,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        on_conflict="store_id",
    ).execute()


def _get_bill_settings_supabase(store_id: int) -> dict:
    rows = (
        _settings_table().select("seal_sign_image, dl_number").eq("store_id", store_id).limit(1).execute()
    ).data or []
    if not rows:
        return {"seal_sign_image": None, "dl_number": None}
    return {
        "seal_sign_image": rows[0].get("seal_sign_image") or None,
        "dl_number": rows[0].get("dl_number") or None,
    }


def _save_dl_number_supabase(store_id: int, dl_number: str) -> None:
    _settings_table().upsert(
        {
            "store_id": store_id,
            "dl_number": dl_number,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        on_conflict="store_id",
    ).execute()