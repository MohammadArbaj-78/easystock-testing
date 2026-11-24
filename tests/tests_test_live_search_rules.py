from core import name_matching as nm
from modules.products import service as products_service


def test_one_letter_shows_only_names_with_a_word_starting_with_it():
    assert nm.search_rank("Aciloc 150 Tablet", "RV1", "a") is not None
    assert nm.search_rank("Crocin Advance", "RV1", "a") is not None      # 2nd word starts with a
    assert nm.search_rank("Paracetamol", "XY9", "a") is None             # "a" only inside the name


def test_two_letters():
    assert nm.search_rank("Aerocort Rotacap", "1", "ar") is None
    assert nm.search_rank("Arkamin", "1", "ar") is not None
    assert nm.search_rank("Cipla Arthro", "1", "ar") is not None
    assert nm.search_rank("Paracetamol", "1", "ar") is None


def test_batch_and_empty():
    assert nm.search_rank("Zyx", "RV26014", "rv2") is not None
    assert nm.search_rank("Zyx", "RV26014", "260") is not None           # 3+ chars may be inside the batch
    assert nm.search_rank("Zyx", "RV26014", "26") is None
    assert nm.search_rank("Zyx", "RV26014", "") == 0


def test_live_products_page_ranks_and_counts():
    rows = [{"name": n, "batch_number": "B"} for n in ("Paracetamol", "Crocin Advance", "Aciloc", "Arkamin")]
    page = products_service.search_products_page_live(1, "a", 2, all_rows=rows)
    assert page["total"] == 3
    assert [r["name"] for r in page["rows"]] == ["Aciloc", "Arkamin"]    # names starting with a first
