"""
Login and signup screen.

This is the only UI a store owner sees before authenticating. It is
intentionally a single, focused screen with two tabs (Login / Sign Up)
rather than separate pages, since the target user is a non-technical
shop owner who should never have to think about navigation before they
are even logged in.

This file only renders UI and calls core.auth - it contains no business
logic of its own (no password hashing, no database access), consistent
with the project's separation between UI and logic.
"""

import streamlit as st

from core.auth import signup, login, create_session_token
from core.session import start_session, save_persistent_session
from core.exceptions import ValidationError, DuplicateMobileError, InvalidCredentialsError
from config.settings import APP_NAME


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


def _render_login_form() -> None:
    """Render the login form and handle submission."""
    with st.form("login_form"):
        mobile_number = st.text_input(
            "Mobile Number",
            placeholder="Enter your 10-digit mobile number",
            max_chars=13,  # allows for spaces/dashes if pasted
        )
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", use_container_width=True)

    if not submitted:
        return

    try:
        store = login(mobile_number, password)
        start_session(
            store_id=store["store_id"],
            store_name=store["store_name"],
            owner_name=store["owner_name"],
        )
        save_persistent_session(create_session_token(store["store_id"]))
        st.rerun()
    except (ValidationError, InvalidCredentialsError) as error:
        st.error(str(error))


def _render_signup_form() -> None:
    """Render the signup form and handle submission."""
    with st.form("signup_form"):
        store_name = st.text_input("Store Name", placeholder="e.g. Sharma Medical Store")
        owner_name = st.text_input("Owner Name", placeholder="e.g. Ramesh Sharma")
        mobile_number = st.text_input(
            "Mobile Number",
            placeholder="Enter your 10-digit mobile number",
            max_chars=13,
        )
        password = st.text_input(
            "Password",
            type="password",
            help="6 to 20 characters",
        )
        submitted = st.form_submit_button("Create Account", use_container_width=True)

    if not submitted:
        return

    try:
        store_id = signup(
            store_name=store_name,
            owner_name=owner_name,
            mobile_number=mobile_number,
            password=password,
        )
        store = login(mobile_number, password)
        start_session(
            store_id=store["store_id"],
            store_name=store["store_name"],
            owner_name=store["owner_name"],
        )
        save_persistent_session(create_session_token(store["store_id"]))
        st.success("Account created successfully!")
        st.rerun()
    except (ValidationError, DuplicateMobileError) as error:
        st.error(str(error))
