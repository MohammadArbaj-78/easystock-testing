"""
Which Low Stock mode the store is in, shared by the Low Stock page and the
Dashboard (kept here so neither has to import the other's screen).

  ON  ("Asli qty save karo", also the default) -> real quantities exist, so
      the Low Stock Alerts work from the stock.
  OFF -> no real quantities: Low Stock means the Diary list (the medicines
      the owner wrote down, with or without an agency).
"""

import time

import streamlit as st

from modules.store_settings import service as store_settings_service

# The Quick Setup switch "Asli qty save karo", kept in the session so the
# database is not asked every time (Quick Setup clears it when it changes).
REAL_QTY_KEY = "ls_real_qty"
REAL_QTY_MAX_AGE_SECONDS = 600

# Same session key the Diary screen keeps its list in (low_stock_diary/ui.py).
DIARY_STATE_KEY = "lsd_state"


def alerts_enabled(store_id: int) -> bool:
    """True when the store keeps real quantities (switch ON, also the default
    for a store that never touched it)."""
    cached = st.session_state.get(REAL_QTY_KEY)
    now = time.time()
    if cached is not None and cached[0] == store_id and now - cached[2] < REAL_QTY_MAX_AGE_SECONDS:
        return cached[1]
    value = bool(store_settings_service.invoice_saves_real_quantity(store_id))
    st.session_state[REAL_QTY_KEY] = (store_id, value, now)
    return value


def diary_rows(store_id: int) -> list:
    """The Diary list (plain + the ones sent to an agency). Shares the Diary
    screen's session copy, so it is always what that screen shows; read from
    the database only when the Diary was not opened yet."""
    from modules.low_stock_diary import service as diary_service

    state = st.session_state.get(DIARY_STATE_KEY)
    if state is None or state.get("store_id") != store_id:
        state = {"store_id": store_id, "rows": diary_service.get_entries(store_id)}
        st.session_state[DIARY_STATE_KEY] = state
    return state["rows"]
