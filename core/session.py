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

--- Persistent Login (Remember Session) ---
This module is also the only place that touches the browser-side
persistent session cookie - the same "one place owns this concern"
reasoning as above, just for the cookie instead of session_state.
save_persistent_session/clear_persistent_session write/clear it via a
tiny, guarded JS snippet (the same components.html pattern app.py's
mobile sidebar auto-close already uses, and the only other sanctioned
use of client-side JS in this codebase - see AI_RULES.md's JavaScript
guardrails); get_saved_session_token reads it back with zero JS, via
Streamlit's native st.context.cookies. This module never decides
whether a token is valid - that's core.auth's job (validate_session_token) -
it only stores and retrieves the opaque string.
"""

import streamlit as st
import streamlit.components.v1 as components

from config.settings import SESSION_STATE_KEY, SESSION_COOKIE_NAME, SESSION_TOKEN_VALIDITY_DAYS


def start_session(store_id: int, store_name: str, owner_name: str) -> None:
    """Begin an authenticated session for a store after successful login
    or signup.

    Args:
        store_id: The authenticated store's primary key.
        store_name: The store's display name, cached here so UI code can
            show a greeting without an extra database lookup on every
            rerun.
        owner_name: The owner's display name.
    """
    st.session_state[SESSION_STATE_KEY] = {
        "store_id": store_id,
        "store_name": store_name,
        "owner_name": owner_name,
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


def end_session() -> None:
    """End the current session (logout).

    Safe to call even if no session exists.
    """
    if SESSION_STATE_KEY in st.session_state:
        del st.session_state[SESSION_STATE_KEY]


def save_persistent_session(token: str) -> None:
    """Persist a session-restore token (from core.auth.create_session_token)
    in a browser cookie, so the session survives closing and reopening
    the browser. Called once, right after start_session(), by
    core.login_ui on successful login/signup.

    Streamlit has no Python API to set a cookie, so this uses the same
    narrowly-scoped, guarded components.html(...) pattern app.py's
    mobile sidebar auto-close already established (see AI_RULES.md's
    JavaScript guardrails) - the JS here does exactly one thing (write
    one cookie with a value supplied entirely from Python) and contains
    no business logic of its own; all validation happens in
    core.auth.validate_session_token.

    Args:
        token: The signed token string to persist.
    """
    max_age_seconds = SESSION_TOKEN_VALIDITY_DAYS * 86400
    components.html(
        f"""
        <script>
        (function() {{
            try {{
                window.parent.document.cookie =
                    "{SESSION_COOKIE_NAME}={token}; max-age={max_age_seconds}; path=/; SameSite=Lax";
            }} catch (e) {{
                // Fail silently - persistent login is a convenience on
                // top of a working password login, never something
                // that should be able to break the app if it can't run.
            }}
        }})();
        </script>
        """,
        height=0,
    )


def clear_persistent_session() -> None:
    """Remove the saved session-restore cookie. Called by app.py's
    Logout button, alongside end_session().

    Setting max-age=0 tells the browser to delete the cookie
    immediately - the next app load will find no cookie at all, exactly
    as if the store had never used Persistent Login.
    """
    components.html(
        f"""
        <script>
        (function() {{
            try {{
                window.parent.document.cookie =
                    "{SESSION_COOKIE_NAME}=; max-age=0; path=/; SameSite=Lax";
            }} catch (e) {{
                // Fail silently, same reasoning as save_persistent_session.
            }}
        }})();
        </script>
        """,
        height=0,
    )


def get_saved_session_token() -> str:
    """Read the saved session-restore cookie, if any.

    Uses Streamlit's native st.context.cookies (read-only, no JS
    involved) - available because the browser already sends this cookie
    with every request once save_persistent_session has set it, exactly
    like any other cookie.

    Returns:
        The saved token string, or None if no session cookie is present.
        This function does not validate the token - core.auth.
        validate_session_token does that; a present-but-invalid token is
        indistinguishable from any other string here, by design.
    """
    return st.context.cookies.get(SESSION_COOKIE_NAME)
