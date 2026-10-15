"""Quick Setup service - thin business layer over the repository."""

from modules.quick_setup import repository as quick_setup_repository
from core import name_matching

def browse_medicines(limit: int = 20) -> list:
    return quick_setup_repository.browse_master_medicines(limit)

def search_medicines(search_term: str, limit: int = 20) -> list:
    return quick_setup_repository.search_master_medicines(search_term, limit)


def search_medicines_all_words(words: list, first_word_prefix: bool = False, limit: int = 60) -> list:
    return quick_setup_repository.search_master_medicines_all_words(words, first_word_prefix, limit)


def get_saved_quantity(store_id: int, name: str) -> float:
    return quick_setup_repository.get_placeholder_quantity(store_id, name)


def save_quantities(store_id: int, name_to_quantity: dict) -> int:
    return quick_setup_repository.save_placeholder_quantities(store_id, name_to_quantity)

def count_medicines() -> int:
    return quick_setup_repository.count_master_medicines()


def browse_medicines_page(page_number: int, page_size: int) -> list:
    return quick_setup_repository.browse_master_medicines_page(page_number, page_size)


def get_last_page(store_id: int) -> int:
    return quick_setup_repository.get_last_browse_page(store_id)


def save_last_page(store_id: int, page_number: int) -> None:
    quick_setup_repository.save_last_browse_page(store_id, page_number)


def find_page_for_letter(letter: str, page_size: int) -> int:
    return quick_setup_repository.find_page_for_letter(letter, page_size)


def count_medicines_starting_with(letter: str) -> int:
    return quick_setup_repository.count_master_medicines_starting_with(letter)


def browse_medicines_starting_with_page(letter: str, page_number: int, page_size: int) -> list:
    return quick_setup_repository.browse_master_medicines_starting_with_page(letter, page_number, page_size)


# ---------------------------------------------------------------------
# Ranked master search (shared by Quick Setup's search box and the Sales
# fallback search, so both always rank and suggest the same way)
# ---------------------------------------------------------------------

# How many master rows each of the three lookups may fetch before ranking.
_PREFIX_FETCH_LIMIT = 60
_CONTAINS_FETCH_LIMIT = 120
_COMBINATION_FETCH_LIMIT = 40

# If a search matches combination medicines, at least this many are shown
# even when single-salt names fill the first page.
_MIN_COMBINATIONS_SHOWN = 2


def search_medicines_ranked(search_term: str, result_limit: int, min_characters: int = 1) -> list:
    """Search the master list: every typed word must be in the name (any
    order), best matches first.

    Ranking: names that start with what was typed come first, then names
    where every typed word starts a word of the name, then the rest;
    within each, single-salt medicines before combinations. Each
    combination medicine the typed words point at gets a single-salt
    suggestion placed right before it ("StayHappi Ambroxol Syrup" before
    "StayHappi Ambroxol+Guaifenesin+Terbutaline ... Syrup").

    Args:
        search_term: Text typed by the owner.
        result_limit: How many ranked medicines to return (the single-salt
            suggestions and a couple of extra combinations come on top).
        min_characters: Shorter text returns [].

    Returns:
        A list of {"name", "manufacturer_name", "composition", "mrp"}
        dicts, one per distinct name.
    """
    term = (search_term or "").strip()
    if len(term) < min_characters:
        return []
    words = name_matching.search_words(term)
    if not words:
        return []

    try:
        rows = (
            search_medicines_all_words(words, True, _PREFIX_FETCH_LIMIT)
            + search_medicines_all_words(words, False, _CONTAINS_FETCH_LIMIT)
            # Combination names start with a brand (StayHappi, Genericart,
            # ...), so alphabetically they come late and could be cut off
            # by the limit above; fetch them separately.
            + search_medicines_all_words(words + ["+"], False, _COMBINATION_FETCH_LIMIT)
        )
    except Exception:
        # Safety net: if the word-based lookup fails for any reason, fall
        # back to the plain one-piece-of-text search that has always been
        # used, so the owner still gets suggestions.
        rows = search_medicines(term, limit=result_limit * 3)

    unique = {}
    for row in rows:
        name = name_matching.clean_spaces(row.get("name"))
        key = name_matching.normalized_name(name)
        if name and key and key not in unique:
            unique[key] = dict(row, name=name)

    def sort_key(row):
        tier = name_matching.match_tier(row["name"], words)
        return (
            3 if tier is None else tier,
            name_matching.is_combination(row["name"]),
            row["name"].lower(),
        )

    ranked = sorted(unique.values(), key=sort_key)
    shown = ranked[:result_limit]

    combinations_shown = sum(1 for row in shown if name_matching.is_combination(row["name"]))
    if combinations_shown < _MIN_COMBINATIONS_SHOWN:
        extra = [
            row for row in ranked[result_limit:]
            if name_matching.is_combination(row["name"])
        ]
        shown = shown + extra[: _MIN_COMBINATIONS_SHOWN - combinations_shown]

    results = []
    already_listed = set(unique)
    for row in shown:
        if name_matching.is_combination(row["name"]):
            for single in name_matching.split_combination(row["name"], words):
                single_key = name_matching.normalized_name(single["name"])
                if single_key in already_listed:
                    continue          # a real master row of that name exists
                already_listed.add(single_key)
                results.append({
                    "name": single["name"],
                    "manufacturer_name": "",
                    "composition": single["salt"],
                    "mrp": None,
                })
        results.append(row)
    return results

