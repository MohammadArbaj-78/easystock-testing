"""core/ai_model.py - which Gemini model a store uses for invoice scanning.

The owner of EasyStock (admin project) sets it, per store or for every store;
the store owners never see or change it. The choice lives in the Supabase
table `store_ai_model` (database/store_ai_model.sql): a row for the store
wins, else the "all stores" row (store_id 0), else GEMINI_MODEL from
config/settings.py.

It is read once per minute per store (kept in memory), so a change made in
the admin app reaches the store within about a minute. If anything goes wrong
(no table, no network, a strange name) the normal GEMINI_MODEL is used - the
scan itself never breaks because of this.
"""

import re
import time

from config.settings import ACTIVE_DB_BACKEND, GEMINI_MODEL

ALL_STORES_ID = 0                 # the row meaning "every store without its own row"
TIER_IDS = {"@high": -1, "@medium": -2}   # a store's row may say "@high"/"@medium": it then uses that level's current model name
CACHE_SECONDS = 60
FAILURE_CACHE_SECONDS = 15        # after a failed read, try again soon

_NAME_PATTERN = re.compile(r"^(models/)?[A-Za-z0-9][A-Za-z0-9._\-]{1,78}$")
_cache = {}                       # store_id -> (read at, model name)


def is_valid_model_name(name) -> bool:
    return bool(_NAME_PATTERN.match(str(name or "").strip()))


def clear_cache() -> None:
    _cache.clear()


def model_for_store(store_id: int) -> str:
    """The model this store scans with (never raises, never returns blank)."""
    if ACTIVE_DB_BACKEND != "supabase":
        return GEMINI_MODEL
    cached = _cache.get(store_id)
    if cached and time.monotonic() - cached[0] < (CACHE_SECONDS if cached[2] else FAILURE_CACHE_SECONDS):
        return cached[1]
    try:
        chosen, ok = _read_choice(store_id), True
    except Exception:
        chosen, ok = None, False
    model = chosen if chosen and is_valid_model_name(chosen) else GEMINI_MODEL
    _cache[store_id] = (time.monotonic(), model, ok)
    return model


def _read_choice(store_id: int):
    from core.supabase_client import get_supabase_client
    rows = (
        get_supabase_client().table("store_ai_model").select("store_id, model")
        .in_("store_id", [int(store_id), ALL_STORES_ID, *TIER_IDS.values()]).execute()
    ).data or []
    by_store = {int(row["store_id"]): str(row.get("model") or "").strip() for row in rows}
    return choose_model(by_store, store_id)


def choose_model(by_store: dict, store_id: int):
    """The model name from the saved rows: the store's own row, else the
    all-stores row; a row may name a model directly or a level ("@high" /
    "@medium" = that level's current name). None when nothing usable is saved."""
    for key in (int(store_id), ALL_STORES_ID):
        value = by_store.get(key) or ""
        if value in TIER_IDS:
            value = by_store.get(TIER_IDS[value]) or ""
        if value:
            return value
    return None
