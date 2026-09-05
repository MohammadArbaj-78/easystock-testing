"""
Session management.

This module is the ONLY place in the application that touches
st.session_state for authentication purposes. Every other module -
every service, every repository, every UI file - must get the current
store's identity through get_current_store_id(), never by reading
st.session_state directly.

This matters more than it might look: in later modules, every repository
query will be scoped by store_id to guarantee one store can never see
another's data. If five different files each read session_state in their
own slightly different way, that guarantee becomes a convention people
have to remember rather than a structural fact about the codebase. By
funneling everything through this one module, "what store is this
request for" has exactly one answer, computed exactly one way.
"""

import streamlit as st

from config.settings import SESSION_STATE_KEY


def start_session(
    store_id: int,
    store_name: str,
    owner_name: str,
    access_token: str = None,
    refresh_token: str = None,
    low_stock_minimum: int = 2,
) -> None:
    """Begin an authenticated session for a store after successful login
    or signup.

    Args:
        store_id: The authenticated store's primary key.
        store_name: The store's display name, cached here so UI code can
            show a greeting without an extra database lookup on every
            rerun.
        owner_name: The owner's display name.
        access_token: The current Supabase Auth session's access token,
            if any (optional and defaults to None so any other existing
            caller of this function continues to work unchanged) -
            stored here, the same place store_id/store_name/owner_name
            already live, so a normal Streamlit rerun/navigation reuses
            it automatically via st.session_state's own persistence,
            with no second, Python-only session mechanism introduced to
            imitate Supabase's.
        refresh_token: The session's refresh token, if any - stored
            alongside access_token for the same reason.
    """
    st.session_state[SESSION_STATE_KEY] = {
        "store_id": store_id,
        "store_name": store_name,
        "owner_name": owner_name,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "low_stock_minimum": low_stock_minimum,
    }


def is_logged_in() -> bool:
    """Check whether a store is currently logged in.

    Returns:
        True if an active session exists, False otherwise.
    """
    return SESSION_STATE_KEY in st.session_state


def get_current_store_id() -> int:
    """Get the store_id of the currently logged-in store.

    Every repository function that reads or writes store-owned data
    (products, sales, invoices, etc.) must call this to obtain its
    store_id - never accept it as a value typed in the UI, and never
    default to "show everything". This is what makes cross-store data
    leakage a structural impossibility rather than something each
    developer has to remember to prevent.

    Returns:
        The store_id of the active session.

    Raises:
        RuntimeError: If called with no active session. This is a
            programming error, not a user-facing one - it means a module
            tried to access store-scoped data before checking
            is_logged_in(), so app.py's routing has a bug.
    """
    if not is_logged_in():
        raise RuntimeError(
            "get_current_store_id() called with no active session. "
            "Calling code must check is_logged_in() before accessing "
            "store-scoped data."
        )
    return st.session_state[SESSION_STATE_KEY]["store_id"]

def get_current_low_stock_minimum() -> int:
    """Get the current store's global Low Stock minimum."""

    if not is_logged_in():
        raise RuntimeError(
            "get_current_low_stock_minimum() called with no active session."
        )

    return st.session_state[SESSION_STATE_KEY].get("low_stock_minimum", 2)

def set_current_low_stock_minimum(value: int) -> None:
    """Update the current session's Low Stock minimum."""

    if not is_logged_in():
        raise RuntimeError(
            "set_current_low_stock_minimum() called with no active session."
        )

    st.session_state[SESSION_STATE_KEY]["low_stock_minimum"] = value

def get_current_store_name() -> str:
    """Get the store_name of the currently logged-in store, for display
    purposes (e.g. greeting the user, page titles).

    Returns:
        The store name of the active session.

    Raises:
        RuntimeError: If called with no active session.
    """
    if not is_logged_in():
        raise RuntimeError(
            "get_current_store_name() called with no active session."
        )
    return st.session_state[SESSION_STATE_KEY]["store_name"]


def get_current_owner_name() -> str:
    """Get the owner_name of the currently logged-in store, for display
    purposes.

    Returns:
        The owner name of the active session.

    Raises:
        RuntimeError: If called with no active session.
    """
    if not is_logged_in():
        raise RuntimeError(
            "get_current_owner_name() called with no active session."
        )
    return st.session_state[SESSION_STATE_KEY]["owner_name"]


def get_current_access_token() -> str:
    """Get the current Supabase Auth session's access token, for
    core.supabase_auth.sign_out() to call at logout.

    Returns:
        The access token stored at login, or None if the active
        session has none (e.g. a session started without Supabase
        Auth, which should no longer happen in normal use post-
        migration, but this stays lenient rather than raising).

    Raises:
        RuntimeError: If called with no active session.
    """
    if not is_logged_in():
        raise RuntimeError(
            "get_current_access_token() called with no active session."
        )
    return st.session_state[SESSION_STATE_KEY].get("access_token")


def end_session() -> None:
    """End the current session (logout).

    Safe to call even if no session exists.
    """
    if SESSION_STATE_KEY in st.session_state:
        del st.session_state[SESSION_STATE_KEY]
