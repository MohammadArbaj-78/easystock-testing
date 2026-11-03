"""core/usage_log.py - har outside-API request ka record (admin dashboard ke liye).

Best effort: agar record likhna fail ho jaye to app ka koi kaam nahi rukta.
Sirf Supabase backend par likhta hai (SQLite par kuch nahi karta).
"""

from config.settings import ACTIVE_DB_BACKEND


def log_api_request(
    store_id: int,
    api_name: str,
    status: str,
    model: str = None,
    duration_seconds: float = None,
    error_message: str = None,
) -> None:
    if ACTIVE_DB_BACKEND != "supabase":
        return
    try:
        from core.supabase_client import get_supabase_client
        get_supabase_client().table("api_usage_log").insert({
            "store_id": store_id,
            "api_name": api_name,
            "status": status,
            "model": model,
            "duration_seconds": duration_seconds,
            "error_message": (error_message or None) and str(error_message)[:300],
        }).execute()
    except Exception:
        pass          # a failed log must never break the real work