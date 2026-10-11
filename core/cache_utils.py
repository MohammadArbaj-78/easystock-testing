"""
Cache invalidation helper - a per-store counter every write bumps and
every cached read includes in its cache key.

Scope: a module-level dict shared by every session/device/user in this
server process - NOT st.session_state (which is per-browser-tab/device
and would never see another device's bump) and NOT a single global
counter (which would invalidate every OTHER store's cache too, on any
one store's write).

Why this matters: a medical store often has MULTIPLE people logged
into the SAME account on different phones/computers at once. A
per-store, process-shared epoch means every device watching THAT
store sees the change on its very next rerun, while a completely
unrelated store's cache is left alone.
"""

_store_epochs = {}


def get_cache_epoch(store_id: int) -> int:
    """Current cache epoch for this store (starts at 0)."""
    return _store_epochs.get(store_id, 0)


def bump_cache_epoch(store_id: int) -> None:
    """Invalidate every @st.cache_data result for this store (and only
    this store) after a successful database write, by advancing its
    epoch."""
    _store_epochs[store_id] = get_cache_epoch(store_id) + 1