"""Quick Setup service - thin business layer over the repository."""

from modules.quick_setup import repository as quick_setup_repository


def search_medicines(search_term: str, limit: int = 20) -> list:
    return quick_setup_repository.search_master_medicines(search_term, limit)


def get_saved_quantity(store_id: int, name: str) -> float:
    return quick_setup_repository.get_placeholder_quantity(store_id, name)


def save_quantities(store_id: int, name_to_quantity: dict) -> int:
    return quick_setup_repository.save_placeholder_quantities(store_id, name_to_quantity)