"""core/usage_log.py - har outside-API request ka record (admin dashboard ke liye).

Best effort: agar record likhna fail ho jaye to app ka koi kaam nahi rukta.
Sirf Supabase backend par likhta hai (SQLite par kuch nahi karta).

Table api_usage_log par main app (anon key) ko sirf INSERT ka haq hai, SELECT ka
nahi. Isliye insert "returning=minimal" se hona chahiye: normal insert nayi row
wapas padhna chahta hai, aur woh SELECT na hone se (RLS) fail ho jata hai - aur
pehle us failure ko chupchap nigal liya jata tha, to record kabhi nahi banta tha.
Ab minimal insert hota hai, aur koi bhi failure app ke logs mein likha jata hai.
"""

import sys

from config.settings import ACTIVE_DB_BACKEND

last_error = None            # the most recent failure text (None = last write was fine)


def _minimal_return():
    """The library's "do not send the row back" value (its place differs between versions)."""
    for module in ("postgrest.base_request_builder", "postgrest.types", "postgrest"):
        try:
            return getattr(__import__(module, fromlist=["ReturnMethod"]), "ReturnMethod").minimal
        except Exception:
            continue
    return "minimal"


def _insert(table, row: dict) -> None:
    try:
        table.insert(row, returning=_minimal_return()).execute()
    except TypeError:                         # a library without the returning option
        table.insert(row).execute()


def log_api_request(
    store_id: int,
    api_name: str,
    status: str,
    model: str = None,
    duration_seconds: float = None,
    error_message: str = None,
) -> None:
    global last_error
    if ACTIVE_DB_BACKEND != "supabase":
        return
    try:
        from core.supabase_client import get_supabase_client
        _insert(get_supabase_client().table("api_usage_log"), {
            "store_id": store_id,
            "api_name": api_name,
            "status": status,
            "model": model,
            "duration_seconds": duration_seconds,
            "error_message": (error_message or None) and str(error_message)[:300],
        })
        last_error = None
    except Exception as error:
        last_error = str(error)
        print(f"[usage_log] record nahi likha ja saka: {error}", file=sys.stderr)   # app never stops for this