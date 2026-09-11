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
    """Call after ANY write (add/edit/delete/sell/invoice save) -
    invalidates every cached read in this session immediately."""
    st.session_state[_CACHE_EPOCH_KEY] = get_cache_epoch() + 1