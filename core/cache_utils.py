"""
Cache invalidation helper - a single, session-scoped counter every
write bumps and every cached read includes in its cache key.
"""

import streamlit as st

_CACHE_EPOCH_KEY = "_cache_epoch"


def get_cache_epoch() -> int:
    """Current cache epoch for this session (starts at 0)."""
    return st.session_state.get(_CACHE_EPOCH_KEY, 0)


def bump_cache_epoch() -> None:
    """
    Clear all Streamlit data caches after a successful
    database write, then increment the cache epoch.
    """

    # Global: clear every @st.cache_data result.
    st.cache_data.clear()

    # Keep the existing epoch mechanism.
    st.session_state[_CACHE_EPOCH_KEY] = get_cache_epoch() + 1