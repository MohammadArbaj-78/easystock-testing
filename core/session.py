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

IMPORTANT - never call save_persistent_session/clear_persistent_session
directly from code that calls st.rerun() shortly afterward (e.g. a
login/signup/logout handler). components.html's iframe loads and runs
its <script> asynchronously in a real browser; st.rerun() tells the
frontend to tear down the current render immediately, and in real-world
conditions (confirmed on Streamlit Cloud + Android Chrome + Add to Home
Screen) the iframe routinely loses that race, so the cookie write/clear
silently never happens even though everything else works. This is why
the feature passed local single-process tests but failed in real
browser usage. Use queue_persistent_session_token/queue_persistent_session_clear
instead (both just stash a session_state flag - synchronous, instant, no
iframe, nothing to race) immediately before an st.rerun(), and call
save_persistent_session/clear_persistent_session (via
pop_persistent_session_token/pop_persistent_session_clear) only from a
render that is NOT itself immediately followed by another st.rerun() -
see app.py's render_main_app/_write_pending_persistent_session_cookie
and its login/signup-screen branch for the actual call sites.
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


_PENDING_TOKEN_KEY = "_pending_persistent_session_token"


def queue_persistent_session_token(token: str) -> None:
    """Queue a token to be written as a cookie on the NEXT render,
    instead of writing it immediately.

    Why this exists: save_persistent_session() renders an iframe whose
    <script> loads and runs asynchronously in the real browser - it is
    not instant the way it looks in-process. Calling
    save_persistent_session() and then immediately calling st.rerun()
    (needed right after login/signup so the UI actually advances to the
    Dashboard) is a race: st.rerun() tells the frontend to discard the
    current render right away, and in real-world conditions the iframe
    routinely hasn't finished loading and executing before that
    teardown happens - so the cookie is never actually set, even though
    everything else (session_state, the token itself) is already
    correct. This is why the feature passed local, synchronous,
    single-process tests but failed in real browser usage (Streamlit
    Cloud, Android Chrome, Add to Home Screen all confirmed to share the
    same underlying app, so this reproduces anywhere - it was never a
    platform-specific cookie-isolation issue).

    The fix: core.login_ui calls this (synchronous, instant, no iframe
    involved - just a session_state write) immediately before its own
    st.rerun(), instead of calling save_persistent_session() there
    directly. app.py's render_main_app() then calls
    pop_persistent_session_token() and, if present, calls
    save_persistent_session() with it - during a render that is *not*
    immediately followed by another st.rerun(), giving the injected
    iframe the rest of that render cycle to actually load and execute.

    Args:
        token: The signed token string to write as a cookie on the next
            render that isn't itself about to be interrupted.
    """
    st.session_state[_PENDING_TOKEN_KEY] = token


def pop_persistent_session_token() -> str:
    """Return and clear any token queued by queue_persistent_session_token.

    Called once per render by app.py's render_main_app(), so a queued
    token is written as a cookie exactly once, not on every subsequent
    rerun of an already-restored session.

    Returns:
        The queued token string, or None if nothing is queued (the
        normal case - most renders have nothing pending; a token is
        only ever queued in the single render right after a fresh
        login/signup).
    """
    return st.session_state.pop(_PENDING_TOKEN_KEY, None)


_PENDING_CLEAR_KEY = "_pending_persistent_session_clear"


def queue_persistent_session_clear() -> None:
    """Queue the saved cookie to be cleared on the NEXT render, instead
    of clearing it immediately - the exact same race described in
    queue_persistent_session_token's docstring applies symmetrically to
    clear_persistent_session(): app.py's Logout button calls
    end_session() then needs st.rerun() right away so the UI actually
    returns to the login screen, and clear_persistent_session()'s
    injected iframe would just as often lose that race and never
    actually run in a real browser.

    app.py's Logout button calls this (synchronous, instant) instead of
    calling clear_persistent_session() directly, immediately before its
    own st.rerun(). The login/signup screen's render then calls
    pop_persistent_session_clear() and, if set, calls
    clear_persistent_session() - during a render that isn't itself
    about to be interrupted by another rerun.
    """
    st.session_state[_PENDING_CLEAR_KEY] = True


def pop_persistent_session_clear() -> bool:
    """Return and clear the pending-clear flag set by
    queue_persistent_session_clear.

    Called once per render by the login/signup screen, so a queued
    clear happens exactly once, not on every render of the login
    screen.

    Returns:
        True if a clear was queued (and should now be acted on), False
        otherwise (the normal case for every ordinary login-screen
        render that isn't immediately following a Logout click).
    """
    return st.session_state.pop(_PENDING_CLEAR_KEY, False)
