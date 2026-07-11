"""
EasyStock - main application entry point.

This file's only responsibility is routing: initialize the database once,
check whether a store is logged in, and show either the login/signup
screen or the main app shell. It deliberately contains no business logic
and no direct database access - if this file starts growing beyond
routing, that's a sign logic is leaking into the wrong layer.
"""

import streamlit as st

from config.settings import APP_NAME
from core.database import initialize_database
from core.session import is_logged_in, get_current_store_name, get_current_owner_name, end_session
from core.login_ui import render_login_signup_screen
from modules.dashboard.ui import render_dashboard
from modules.products.ui import render_products_page
from modules.alerts.ui import render_expiry_alerts_page
from modules.alerts.low_stock_ui import render_low_stock_alerts_page
from modules.invoice_scan.upload_ui import render_invoice_scan_page

st.set_page_config(
    page_title=APP_NAME,
    page_icon="📦",
    layout="centered",
)

# Schema creation is idempotent (CREATE TABLE IF NOT EXISTS), so calling
# this on every script run is safe and requires no separate setup step -
# important for an MVP that needs to "just work" the first time a store
# opens the app, including on a fresh Streamlit Cloud deployment.
initialize_database()

# Maps a nav label to its module's render function. Adding a new module
# to the app means adding one entry here - app.py itself doesn't grow
# any routing logic per module.
NAV_PAGES = {
    "📊 Dashboard": render_dashboard,
    "💊 Products": render_products_page,
    "🧾 Invoice Scan": render_invoice_scan_page,
    "⏰ Expiry Alerts": render_expiry_alerts_page,
    "📦 Low Stock": render_low_stock_alerts_page,
}


def render_main_app() -> None:
    """Render the main app shell for a logged-in store: sidebar
    navigation plus whichever module page is currently selected.
    """
    with st.sidebar:
        st.markdown(f"### {get_current_store_name()}")
        st.caption(f"Owner: {get_current_owner_name()}")
        st.divider()
        selected_page = st.radio("Navigate", list(NAV_PAGES.keys()), label_visibility="collapsed")
        st.divider()
        if st.button("Logout", use_container_width=True):
            end_session()
            st.rerun()

    st.title(f"📦 {APP_NAME}")
    NAV_PAGES[selected_page]()


if is_logged_in():
    render_main_app()
else:
    render_login_signup_screen()
