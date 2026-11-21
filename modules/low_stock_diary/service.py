"""
Low Stock Diary business logic (no Streamlit, no SQL).

The owner notes down a medicine that is finished or running low. Suggestions
come the same way as the Sales search: the store's own medicines first, else
the medicine list, else "add what you typed".
"""

from urllib.parse import quote

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


def assign_to_agency(store_id: int, diary_ids: list, agency_id: int) -> None:
    """Put these diary medicines on an agency's "Mangwana hai" list."""
    repository.set_agency(store_id, diary_ids, agency_id)


def return_to_diary(store_id: int, diary_ids: list) -> None:
    """Take these medicines off their agency's list, back to the plain diary."""
    repository.set_agency(store_id, diary_ids, None)


def split_rows(rows: list) -> tuple:
    """(plain diary rows, {agency_id: rows on that agency's list}); the order
    of each list stays as given (newest first)."""
    plain, by_agency = [], {}
    for row in rows:
        if row.get("agency_id") is None:
            plain.append(row)
        else:
            by_agency.setdefault(int(row["agency_id"]), []).append(row)
    return plain, by_agency


def agency_list(store_id: int, agency_id: int) -> list:
    """The medicines on one agency's "Mangwana hai" list, oldest first
    (read fresh from the database)."""
    _, by_agency = split_rows(repository.list_entries(store_id))
    return list(reversed(by_agency.get(int(agency_id), [])))


def clear_agency_list(store_id: int, agency_id: int) -> int:
    """The order is done: delete this agency's whole list. Returns how many."""
    ids = [row["diary_id"] for row in agency_list(store_id, agency_id)]
    repository.delete_entries(store_id, ids)
    return len(ids)


def order_message(agency_name: str, names: list) -> str:
    """The text to send / copy: a numbered list of medicines."""
    lines = [f"{number}. {name}" for number, name in enumerate(names, start=1)]
    return f"Namaste {agency_name},\nMujhe ye dawai chahiye:\n" + "\n".join(lines) + "\nThank you."


def whatsapp_url(text: str) -> str:
    """Opens the WhatsApp app itself with the text ready (the owner picks who to
    send to); no browser page in between."""
    return "whatsapp://send?text=" + quote(text)