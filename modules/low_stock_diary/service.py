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


MAX_QTY = 99999


def parse_qty_payload(text) -> dict:
    """What the page sends after the owner set quantities: "<counter>;id:qty,id:qty".
    Returns {diary_id: qty}; a broken piece is ignored, a qty is kept between
    0 and MAX_QTY."""
    result = {}
    _, _, body = str(text or "").partition(";")
    for part in body.split(","):
        left, _, right = part.partition(":")
        try:
            diary_id, qty = int(left), int(right)
        except ValueError:
            continue
        if diary_id > 0:
            result[diary_id] = max(0, min(qty, MAX_QTY))
    return result


def set_quantities(store_id: int, quantities: dict) -> dict:
    """Save quantities {diary_id: qty}; 0 means "not set" (stored empty).
    Returns {"status": "saved", "saved": {diary_id: qty or None}} or
    {"status": "error", "error": text} (for example the qty column is not
    created yet) - it never raises."""
    cleaned = {int(diary_id): (int(qty) or None) for diary_id, qty in quantities.items()}
    if not cleaned:
        return {"status": "saved", "saved": {}}
    try:
        repository.set_quantities(store_id, cleaned)
    except Exception as error:
        return {"status": "error", "error": str(error)}
    return {"status": "saved", "saved": cleaned}


def line_text(row: dict) -> str:
    """One medicine as it is sent to the agency: "Name - qty" (just the name
    when no quantity is set)."""
    qty = row.get("qty")
    return f"{row['name']} - {int(qty)}" if qty else str(row["name"])


def clean_agency_name(text) -> str:
    """The agency name the owner typed, or "" when it is too short / has no letter."""
    import re
    cleaned = name_matching.clean_spaces(text)
    if not 2 <= len(cleaned) <= 100 or not re.search(r"[A-Za-z0-9]", cleaned):
        return ""
    return cleaned


def add_agency(store_id: int, text) -> dict:
    """Create an agency by name (or find the one that already has this name).
    {"status": "ok", "agency_id", "name"} | "invalid" | "error"."""
    name = clean_agency_name(text)
    if not name:
        return {"status": "invalid"}
    try:
        from modules.agencies import repository as agencies_repository
        agency_id = agencies_repository.find_or_create_agency(store_id, name)
    except Exception as error:
        return {"status": "error", "error": str(error)}
    return {"status": "ok", "agency_id": agency_id, "name": name}


def order_message(agency_name: str, names: list) -> str:
    """The text to send / copy: a numbered list of medicines."""
    lines = [f"{number}. {name}" for number, name in enumerate(names, start=1)]
    return f"Namaste {agency_name},\nMujhe ye dawai chahiye:\n" + "\n".join(lines) + "\nThank you."


def whatsapp_url(text: str, mobile: str = None) -> str:
    """Opens the WhatsApp app itself with the text ready, no browser page in
    between. With the agency's saved number the chat of that agency opens
    directly; without it the owner picks who to send to."""
    if mobile:
        return f"whatsapp://send?phone=91{mobile}&text=" + quote(text)
    return "whatsapp://send?text=" + quote(text)


def agency_mobiles(store_id: int) -> dict:
    """{agency_id: mobile}. A problem here (for example the agency_contacts
    table is not created yet) just means "no numbers saved"."""
    try:
        return repository.list_agency_mobiles(store_id)
    except Exception:
        return {}


def save_agency_mobile(store_id: int, agency_id: int, text: str) -> dict:
    """{"status": "saved", "mobile"} | "bad_mobile" | "error"."""
    from modules.udhar.service import normalize_mobile
    mobile = normalize_mobile(text)
    if mobile is None:
        return {"status": "bad_mobile"}
    try:
        repository.set_agency_mobile(store_id, agency_id, mobile)
    except Exception as error:
        return {"status": "error", "error": str(error)}
    return {"status": "saved", "mobile": mobile}