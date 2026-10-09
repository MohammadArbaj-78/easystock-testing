"""Quick Setup service - thin business layer over the repository."""

from modules.quick_setup import repository as quick_setup_repository

def browse_medicines(limit: int = 20) -> list:
    return quick_setup_repository.browse_master_medicines(limit)

def search_medicines(search_term: str, limit: int = 20) -> list:
    return quick_setup_repository.search_master_medicines(search_term, limit)


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