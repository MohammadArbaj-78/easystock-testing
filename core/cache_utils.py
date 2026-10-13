"""
Cache invalidation helper.

Reverted to the simple, proven-reliable design: any write anywhere
calls bump_cache_epoch(), which clears EVERY @st.cache_data result in
the whole app. This is the "wasteful but always correct" approach -
at this project's current scale (a handful of validation stores) the
extra recomputation cost is negligible, and it completely avoids the
class of bug the fancier per-store-epoch design kept causing: a single
cached read anywhere that didn't correctly include the epoch in its
key would silently never refresh. One missed wiring = a stale feature
that's hard to notice until a user reports it.

Accepts (and ignores) an optional store_id/arg so every existing call
site - get_cache_epoch(store_id), bump_cache_epoch(store_id), or the
old no-argument form - keeps working with ZERO other files touched.
"""

import streamlit as st

_CACHE_EPOCH_KEY = "_cache_epoch"


def get_cache_epoch(*_args, **_kwargs) -> int:
    """Current cache epoch (starts at 0). Any arguments are accepted
    and ignored - kept only so existing get_cache_epoch(store_id)
    calls don't need to be rewritten."""
    return st.session_state.get(_CACHE_EPOCH_KEY, 0)


def bump_cache_epoch(*_args, **_kwargs) -> None:
    """Clear every @st.cache_data result in the app, then advance the
    epoch. Any arguments are accepted and ignored - kept only so
    existing bump_cache_epoch(store_id) calls don't need rewriting."""
    st.cache_data.clear()
    st.session_state[_CACHE_EPOCH_KEY] = get_cache_epoch() + 1