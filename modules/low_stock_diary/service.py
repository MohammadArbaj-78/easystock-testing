"""
Low Stock Diary business logic (no Streamlit, no SQL).

The owner notes down a medicine that is finished or running low. Suggestions
come the same way as the Sales search: the store's own medicines first, else
the medicine list, else "add what you typed".
"""

from core import name_matching
from modules.low_stock_diary import repository
from modules.sales import service as sales_service

SUGGESTION_LIMIT = 10


def get_entries(store_id: int) -> list:
    """The diary, newest first."""
    return repository.list_entries(store_id)


def add_medicine(store_id: int, name: str, known_rows: list = None) -> dict:
    """Put a medicine in the diary.

    known_rows: the diary rows the caller already has - then the list is not
    read again (a stale list is still safe: the database refuses a duplicate).

    Returns {"status": "added" | "exists" | "invalid", "name": cleaned name,
    "diary_id": new id (only when added)}.
    "exists": the medicine (same name, ignoring case / spaces / punctuation)
    is already in the diary - nothing is added twice.
    """
    is_valid, cleaned = name_matching.is_valid_new_medicine_name(name)
    if not is_valid:
        return {"status": "invalid", "name": name_matching.clean_spaces(name)}
    key = name_matching.normalized_name(cleaned)
    current = known_rows if known_rows is not None else repository.list_entries(store_id)
    if any(name_matching.normalized_name(row["name"]) == key for row in current):
        return {"status": "exists", "name": cleaned}
    try:
        diary_id = repository.add_entry(store_id, cleaned, key)
    except Exception as error:
        text = str(error).lower()
        if "duplicate" in text or "unique" in text or "23505" in text:
            return {"status": "exists", "name": cleaned}
        raise
    return {"status": "added", "name": cleaned, "diary_id": diary_id}


def remove_medicines(store_id: int, diary_ids: list) -> None:
    repository.delete_entries(store_id, list(diary_ids))


def store_medicine_names(catalog: list) -> list:
    """One row per medicine of the store (all its lots together, 0 stock
    included): [{"name", "quantity"}] - a small list kept for searching."""
    by_key = {}
    for row in catalog:
        name = name_matching.clean_spaces(row.get("name"))
        key = name_matching.normalized_name(name)
        if not key:
            continue
        try:
            quantity = float(row.get("quantity") or 0)
        except (TypeError, ValueError):
            quantity = 0.0
        if key in by_key:
            by_key[key]["quantity"] += quantity
        else:
            by_key[key] = {"name": name, "quantity": quantity}
    return list(by_key.values())


def suggest_from_store(term: str, store_names: list):
    """The store's own medicines that match, best match first, or None if
    there is none (then the caller asks suggest() without them).
    {"kind": "store", "items": [{"name", "quantity"}]}"""
    words = name_matching.search_words(term)
    if not words:
        return {"kind": "none", "items": []}
    ranked = []
    for item in store_names:
        tier = name_matching.match_tier(item["name"], words)
        if tier is not None:
            ranked.append((tier, item["name"].lower(), item))
    if not ranked:
        return None
    ranked.sort(key=lambda entry: (entry[0], entry[1]))
    return {"kind": "store", "items": [entry[2] for entry in ranked[:SUGGESTION_LIMIT]]}


def suggest(term: str, store_names: list) -> dict:
    """What the search box offers for what was typed.

    {"kind": "store",  "items": [{"name", "quantity"}]}   - the store's own medicines
    {"kind": "master", "items": [{"name", "composition"}]} - the medicine list
    {"kind": "new",    "items": [], "name": cleaned}      - add what was typed
    {"kind": "none",   "items": []}
    """
    result = suggest_from_store(term, store_names)
    if result is not None:
        return result
    master = sales_service.search_master_medicines(term)
    if master:
        return {"kind": "master", "items": master}
    is_valid, cleaned = name_matching.is_valid_new_medicine_name(term)
    if is_valid:
        return {"kind": "new", "items": [], "name": cleaned}
    return {"kind": "none", "items": []}