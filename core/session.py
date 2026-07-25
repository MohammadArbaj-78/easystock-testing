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
its <script> asynchronously in a real browser with no completion signal
Python can wait on, and real-world propagation of the resulting cookie
write/clear is a documented, unresolved Streamlit limitation (no native
st.set_cookie exists; see streamlit/streamlit#9421 - other cookie-JS
approaches in the Streamlit ecosystem report the same unreliability,
worse under added network latency and on some mobile browsers) - a
single fire-and-forget attempt, even one not raced by an immediate
st.rerun(), is not reliably guaranteed to land. This is why the feature
passed local single-process tests but still failed in real browser
usage even after the first (rerun-timing) fix.

The mitigation: don't rely on exactly one attempt succeeding. Use
queue_persistent_session_token/queue_persistent_session_clear (both just
stash a session_state flag - synchronous, instant, no iframe, nothing to
race) immediately before an st.rerun(), same as before. But instead of
writing/clearing the cookie exactly once on the next render,
app.py's _sync_persistent_session_cookie calls
get_persistent_session_token/save_persistent_session on every single
render while logged in, and clear_persistent_session on every render
while not logged in - repeating an idempotent, side-effect-free action
many times across a session turns one low-probability opportunity into
many, at negligible cost (Streamlit already re-renders the whole page on
every interaction regardless).
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
    print(f"[PERSISTENT_LOGIN_DEBUG] start_session: entered - input store_id={store_id}, store_name={store_name!r}, owner_name={owner_name!r}")
    st.session_state[SESSION_STATE_KEY] = {
        "store_id": store_id,
        "store_name": store_name,
        "owner_name": owner_name,
    }
    print(f"[PERSISTENT_LOGIN_DEBUG] start_session: session_state immediately after start_session() = {dict(st.session_state)}")


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

    Uses height=1 (not 0): still visually imperceptible, but removes
    any risk of a zero-sized/zero-area element being treated
    differently by a browser's rendering or script-execution scheduling
    than a normally-laid-out one - a defensive, zero-cost precaution
    given real-world propagation of this kind of cookie write is a
    documented, unresolved Streamlit limitation (see
    get_persistent_session_token's docstring).

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
        height=1,
    )


def clear_persistent_session() -> None:
    """Remove the saved session-restore cookie. Called on every render
    of the login/signup screen while no session is active (app.py's
    _sync_persistent_session_cookie) - see get_persistent_session_token's
    docstring for why this repeats instead of firing once.

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
        height=1,
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
    token = st.context.cookies.get(SESSION_COOKIE_NAME)
    print("[PERSISTENT_LOGIN_DEBUG] get_saved_session_token: entered")
    print(f"[PERSISTENT_LOGIN_DEBUG] get_saved_session_token: cookie read from st.context.cookies? {'YES' if token else 'NO'}")
    if token:
        print(f"[PERSISTENT_LOGIN_DEBUG] get_saved_session_token: token (first 15 chars) = {token[:15]}")
    print(f"[PERSISTENT_LOGIN_DEBUG] get_saved_session_token: output returned = {'<token present>' if token else 'None'}")
    return token


_PENDING_TOKEN_KEY = "_pending_persistent_session_token"


def queue_persistent_session_token(token: str) -> None:
    """Record this session's token so it can be written as a cookie
    repeatedly across renders, instead of writing it immediately.

    Why this exists: save_persistent_session() renders an iframe whose
    <script> loads and runs asynchronously in the real browser with no
    completion signal Python can wait on - real-world propagation of the
    resulting cookie write is a documented, unresolved Streamlit
    limitation (see get_persistent_session_token's docstring), not
    something a single well-timed attempt reliably solves. Calling
    save_persistent_session() directly from a login/signup/logout
    handler that then immediately calls st.rerun() makes this worse (the
    frontend discards the current render right away, cutting the
    already-unreliable attempt off even earlier) - but avoiding that
    alone was not sufficient by itself.

    The fix: core.login_ui calls this (synchronous, instant, no iframe
    involved - just a session_state write) immediately before its own
    st.rerun(), instead of calling save_persistent_session() there
    directly. app.py's _sync_persistent_session_cookie then calls
    get_persistent_session_token() and, if present, calls
    save_persistent_session() with it on every single render while
    logged in (not just once) - turning one low-probability opportunity
    into many across the session, at negligible cost.

    Args:
        token: The signed token string to keep (re-)writing as a cookie
            for the rest of this session.
    """
    st.session_state[_PENDING_TOKEN_KEY] = token


def pop_persistent_session_token() -> str:
    """Return and clear any token queued by queue_persistent_session_token.

    Deprecated in favor of get_persistent_session_token (below) -
    superseded now that the cookie write repeats on every render
    instead of firing exactly once (see that function's docstring for
    why). Kept only so nothing calls a now-nonexistent name; nothing in
    this codebase calls it anymore.
    """
    return st.session_state.pop(_PENDING_TOKEN_KEY, None)


def get_persistent_session_token() -> str:
    """Return the current session's token queued by
    queue_persistent_session_token, WITHOUT clearing it.

    Called on every render while logged in (app.py's
    _sync_persistent_session_cookie), not just once, so the cookie write
    gets many independent opportunities to actually execute in the
    browser instead of exactly one. This matters because a plain
    components.html() injection has no completion signal Python can
    wait on, and real-world propagation of a resulting document.cookie
    write is a well-documented, unresolved Streamlit limitation (no
    native st.set_cookie exists as of this writing; see
    streamlit/streamlit#9421) - even purpose-built cookie-management
    components report the same unreliability. Re-issuing an identical
    cookie write on every render is harmless (idempotent) and costs
    nothing extra, since Streamlit already re-renders the full page on
    every interaction regardless - it just turns one low-probability
    opportunity into many, across however many renders happen before
    the user actually closes the app.

    Returns:
        The token string, or None if this session has none yet (no
        login/restore has happened in this session).
    """
    return st.session_state.get(_PENDING_TOKEN_KEY)


_PENDING_CLEAR_KEY = "_pending_persistent_session_clear"


def queue_persistent_session_clear() -> None:
    """Record that a Logout just happened, for exactly one purpose: so
    the very next render skips attempting to restore a session from the
    (not-yet-cleared, from this session's point of view) saved cookie -
    see pop_persistent_session_clear and app.py's routing.

    This does NOT trigger the actual cookie-clearing write itself -
    that now happens unconditionally on every render where no session
    is active (app.py's _sync_persistent_session_cookie calls
    clear_persistent_session() every such render, repeating it for the
    same reliability reasons documented in
    get_persistent_session_token's docstring), so a queued clear here
    doesn't need to be "acted on" once and then forgotten the way it
    used to.

    Without this guard: app.py's Logout button calls end_session() then
    st.rerun() right away. st.context.cookies still reflects this
    WebSocket session's ORIGINAL page-load cookies (a cookie clear
    written mid-session doesn't retroactively update it), so the very
    next render would still see the old, still-cryptographically-valid
    token and silently restore the session right back - defeating the
    logout the user just performed.
    """
    st.session_state[_PENDING_CLEAR_KEY] = True


def pop_persistent_session_clear() -> bool:
    """Return and clear the "a Logout just happened" flag set by
    queue_persistent_session_clear.

    Called once per render, at the top of app.py's routing, purely to
    decide whether to skip this one render's restore-from-cookie
    attempt - not to decide whether to clear the cookie itself (that
    now happens unconditionally on every not-logged-in render; see
    queue_persistent_session_clear's docstring).

    Returns:
        True if a Logout just happened (this is the very next render
        after it), False otherwise (the normal case for every other
        render).
    """
    return st.session_state.pop(_PENDING_CLEAR_KEY, False)
