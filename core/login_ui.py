"""
Login and signup screen.

This is the only UI a store owner sees before authenticating. It is
intentionally a single, focused screen with two tabs (Login / Sign Up)
rather than separate pages, since the target user is a non-technical
shop owner who should never have to think about navigation before they
are even logged in - unchanged from before this migration.

Migration note: this file now calls core.supabase_auth (Supabase Auth,
Email + Password) instead of the removed core.auth (custom mobile
number + bcrypt password). The two-tab layout, the "only renders UI, no
business logic of its own" rule, and app.py's routing around this
screen are all otherwise unchanged - only the fields (mobile number ->
email) and the module called on submit changed.

Requirement 2 addition: after a successful login/signup, the Supabase
refresh token is also written to the browser's localStorage, so
app.py's startup-restoration block can silently re-authenticate on a
fresh browser connection (a full close/reopen) without asking the user
to log in again - see _persist_refresh_token_to_browser()'s own
docstring for why this needs a small JS bridge rather than pure Python.
"""

import time
import streamlit as st
import streamlit.components.v1 as components

from core.supabase_auth import sign_up_and_create_store, sign_in_and_resolve_store
from core.session import start_session
from core.exceptions import ValidationError, SupabaseAuthError, SupabaseConfigError
from config.settings import APP_NAME, LOCALSTORAGE_REFRESH_TOKEN_KEY


def render_login_signup_screen() -> None:
    """Render the combined login/signup screen.

    Called by app.py whenever there is no active session. On successful
    login or signup, starts a session and triggers a rerun so app.py's
    routing immediately shows the main app instead of this screen.
    """
    st.title(f"📦 {APP_NAME}")
    st.caption("Simple inventory management for your medical store")

    login_tab, signup_tab = st.tabs(["Login", "Sign Up"])

    with login_tab:
        _render_login_form()

    with signup_tab:
        _render_signup_form()


def _persist_refresh_token_to_browser(refresh_token: str) -> None:
    """Write the Supabase refresh token to the browser's localStorage
    (Requirement 2), so it survives a full browser close/reopen - a
    plain Python variable/st.session_state cannot, since both live only
    for the current WebSocket connection.

    Deliberately writes ONLY the refresh token, never the access token
    or the password - the smallest piece of data that
    core.supabase_auth.restore_session() needs to silently
    re-authenticate later. Uses a zero-height components.html() call,
    the same JS-bridge mechanism app.py's own mobile-sidebar-autoclose
    feature already uses elsewhere in this project - no new dependency.
    """
    components.html(
        f"""
        <script>
        try {{
            localStorage.setItem({LOCALSTORAGE_REFRESH_TOKEN_KEY!r}, {refresh_token!r});
        }} catch (e) {{
            // localStorage can be unavailable (private browsing, some
            // embedded browsers) - persistence is a convenience, never
            // a requirement for login itself to have already succeeded.
        }}
        </script>
        """,
        height=0,
    )


def _render_login_form() -> None:
    """Render the login form and handle submission."""
    with st.form("login_form"):
        email = st.text_input("Email", placeholder="you@example.com")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", use_container_width=True)

    if not submitted:
        return

    try:
        store = sign_in_and_resolve_store(email, password)
        start_session(
            store_id=store["store_id"],
            store_name=store["store_name"],
            owner_name=store["owner_name"],
            access_token=store["access_token"],
            refresh_token=store["refresh_token"],
            low_stock_minimum=store["low_stock_minimum"],
        )
        _persist_refresh_token_to_browser(store["refresh_token"])
        time.sleep(0.4)
        st.rerun()
    except (ValidationError, SupabaseAuthError, SupabaseConfigError) as error:
        st.error(str(error))


def _render_signup_form() -> None:
    """Render the signup form and handle submission."""
    with st.form("signup_form"):
        store_name = st.text_input("Store Name", placeholder="e.g. Sharma Medical Store")
        owner_name = st.text_input("Owner Name", placeholder="e.g. Ramesh Sharma")
        email = st.text_input("Email", placeholder="you@example.com")
        password = st.text_input(
            "Password",
            type="password",
            help="6 to 20 characters",
        )
        submitted = st.form_submit_button("Create Account", use_container_width=True)

    if not submitted:
        return

    try:
        store = sign_up_and_create_store(
            store_name=store_name,
            owner_name=owner_name,
            email=email,
            password=password,
        )
        start_session(
            store_id=store["store_id"],
            store_name=store["store_name"],
            owner_name=store["owner_name"],
            access_token=store["access_token"],
            refresh_token=store["refresh_token"],
            low_stock_minimum=store["low_stock_minimum"],
        )
        _persist_refresh_token_to_browser(store["refresh_token"])
        time.sleep(0.4)
        st.success("Account created successfully!")
        st.rerun()
    except (ValidationError, SupabaseAuthError, SupabaseConfigError) as error:
        st.error(str(error))
