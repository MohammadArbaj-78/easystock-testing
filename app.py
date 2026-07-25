"""
EasyStock - main application entry point.

This file's only responsibility is routing: initialize the database once,
check whether a store is logged in (including restoring one from a saved
Persistent Login cookie, if any - see _restore_persistent_session_if_any),
and show either the login/signup screen or the main app shell. It
deliberately contains no business logic and no direct database access -
if this file starts growing beyond routing, that's a sign logic is
leaking into the wrong layer.
"""

import streamlit as st
import streamlit.components.v1 as components

from config.settings import APP_NAME
from core.database import initialize_database
from core.auth import validate_session_token
from core.session import (
    is_logged_in,
    get_current_store_name,
    get_current_owner_name,
    start_session,
    end_session,
    get_saved_session_token,
    save_persistent_session,
    get_persistent_session_token,
    queue_persistent_session_token,
    clear_persistent_session,
    queue_persistent_session_clear,
    pop_persistent_session_clear,
)
from core.login_ui import render_login_signup_screen
from modules.dashboard.ui import render_dashboard
from modules.products.ui import render_products_page
from modules.alerts.ui import render_expiry_alerts_page
from modules.alerts.low_stock_ui import render_low_stock_alerts_page
from modules.invoice_scan.upload_ui import render_invoice_scan_page
from modules.sales.ui import render_sales_page

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
    "🛒 Sales": render_sales_page,
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
            queue_persistent_session_clear()
            st.rerun()

        _render_mobile_sidebar_css()
        _render_mobile_sidebar_autoclose()

    st.title(f"📦 {APP_NAME}")
    NAV_PAGES[selected_page]()


def _render_mobile_sidebar_css() -> None:
    """Mobile-only sidebar polish: bigger touch targets and slightly
    larger text on the nav items. Entirely inside
    @media (max-width: 768px), so desktop spacing/fonts are completely
    unaffected. Scoped to [data-testid="stSidebar"] [role="radiogroup"]
    label - the sidebar's own nav radio rows - so nothing outside the
    sidebar, and no other st.radio elsewhere in the app, is touched.
    role="radiogroup" is a standard ARIA attribute Streamlit's radio
    widget already provides, not an internal/unstable test id.
    """
    st.markdown(
        """
        <style>
        @media (max-width: 768px) {
            [data-testid="stSidebar"] [role="radiogroup"] label {
                min-height: 3rem !important;
                padding: 0.85rem 0.6rem !important;
                display: flex !important;
                align-items: center !important;
                font-size: 1.12em !important;
                line-height: 1.4 !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_mobile_sidebar_autoclose() -> None:
    """Auto-close the sidebar after tapping a nav item, on mobile only.

    Streamlit has no public Python API to collapse the sidebar, so this
    uses a tiny, invisible (height=0) component to detect - on the
    browser side - that the selected nav item just changed, and if the
    viewport is mobile-width, programmatically click Streamlit's own
    native sidebar-collapse control (the same control a user would tap
    themselves). Desktop is unaffected: the collapse click is only
    attempted when window.innerWidth is at or below the same 768px
    breakpoint used above, and this never touches desktop's own sidebar
    state.

    This relies on Streamlit's current internal DOM structure for the
    collapse button (best-effort selectors, several are tried), which
    is not part of Streamlit's public API and could require updating on
    a future Streamlit version upgrade. It is written to fail silently:
    if the collapse control can't be found, navigation still works
    exactly as before, the sidebar just doesn't auto-close.

    A previously-selected-label is tracked in the browser's own
    sessionStorage (survives Streamlit's rerender, cleared when the tab
    closes) so this only fires right after an actual navigation change -
    never on first page load, before the user has tapped anything.
    """
    components.html(
        """
        <script>
        (function() {
            try {
                var doc = window.parent.document;
                var STORAGE_KEY = "easystock_last_nav_selection";

                function getSelectedLabel() {
                    var checked = doc.querySelector(
                        '[data-testid="stSidebar"] [role="radiogroup"] input:checked'
                    );
                    if (!checked) return null;
                    var label = checked.closest('label');
                    return label ? label.innerText.trim() : null;
                }

                function collapseSidebarIfMobile() {
                    if (window.parent.innerWidth > 768) return;
                    var selectors = [
                        '[data-testid="stSidebarCollapseButton"] button',
                        '[data-testid="stSidebarCollapseButton"]',
                        '[data-testid="stSidebar"] button[kind="header"]'
                    ];
                    for (var i = 0; i < selectors.length; i++) {
                        var el = doc.querySelector(selectors[i]);
                        if (el) { el.click(); break; }
                    }
                }

                var current = getSelectedLabel();
                var last = window.parent.sessionStorage.getItem(STORAGE_KEY);
                if (current && last && current !== last) {
                    collapseSidebarIfMobile();
                }
                if (current) {
                    window.parent.sessionStorage.setItem(STORAGE_KEY, current);
                }
            } catch (e) {
                // Fail silently - this is a best-effort mobile enhancement
                // and must never break navigation if it can't run.
            }
        })();
        </script>
        """,
        height=0,
    )


def _sync_persistent_session_cookie() -> None:
    """Keep the browser's "Remember Session" cookie in sync with the
    current session on every single render - not just once, right after
    login. See core.session.get_persistent_session_token's docstring for
    why a single fire-and-forget attempt is not reliably enough:
    real-world propagation of a components.html()-injected cookie
    write/clear is a documented, unresolved Streamlit limitation, so
    this repeats the same idempotent action every render instead,
    turning one low-probability opportunity into many. Called once,
    unconditionally, at the very end of this file's routing, after the
    screen for this render has already been decided.
    """
    if is_logged_in():
        token = get_persistent_session_token()
        if token:
            save_persistent_session(token)
    else:
        clear_persistent_session()


def _restore_persistent_session_if_any() -> None:
    """If no session is active yet, try to restore one from a saved
    "Remember Session" cookie (Persistent Login) before deciding which
    screen to show. Never shows an error and never blocks rendering - a
    missing, expired, or invalid saved cookie just means "show the
    normal login screen", exactly as if the feature didn't exist.
    """
    print("[PERSISTENT_LOGIN_DEBUG] _restore_persistent_session_if_any: entered")
    if is_logged_in():
        print("[PERSISTENT_LOGIN_DEBUG] _restore_persistent_session_if_any: exiting early - already logged in")
        return
    saved_token = get_saved_session_token()
    print(f"[PERSISTENT_LOGIN_DEBUG] _restore_persistent_session_if_any: saved_token received = {'<token present>' if saved_token else 'None'}")
    if not saved_token:
        print("[PERSISTENT_LOGIN_DEBUG] _restore_persistent_session_if_any: exiting early - no saved token")
        return
    restored = validate_session_token(saved_token)
    print(f"[PERSISTENT_LOGIN_DEBUG] _restore_persistent_session_if_any: validate_session_token output = {restored}")
    if restored is None:
        print("[PERSISTENT_LOGIN_DEBUG] _restore_persistent_session_if_any: exiting early - token invalid (see validate_session_token logs above for exact reason)")
        return
    start_session(
        store_id=restored["store_id"],
        store_name=restored["store_name"],
        owner_name=restored["owner_name"],
    )
    print("[PERSISTENT_LOGIN_DEBUG] _restore_persistent_session_if_any: start_session() called = YES")
    # Keep this (restored) session's token available so
    # _sync_persistent_session_cookie keeps re-asserting/refreshing the
    # cookie on this session's later renders too, not just on a fresh
    # login - the same reliability reasoning applies equally here.
    queue_persistent_session_token(saved_token)
    print("[PERSISTENT_LOGIN_DEBUG] _restore_persistent_session_if_any: exiting - restore completed successfully")


print("[PERSISTENT_LOGIN_DEBUG] === app.py routing: entered ===")

_just_logged_out = pop_persistent_session_clear()
print(f"[PERSISTENT_LOGIN_DEBUG] app.py routing: _just_logged_out = {_just_logged_out}")

if not _just_logged_out:
    # Only attempt to restore from a saved cookie when this render is
    # NOT the one immediately following a Logout click - otherwise the
    # cookie (not yet cleared from this session's point of view) would
    # still be sitting there and silently log the store back in,
    # defeating the logout that was just requested.
    _restore_persistent_session_if_any()
else:
    print("[PERSISTENT_LOGIN_DEBUG] app.py routing: skipped _restore_persistent_session_if_any() because _just_logged_out is True")

print(f"[PERSISTENT_LOGIN_DEBUG] app.py routing: session_state immediately before routing = {dict(st.session_state)}")
print(f"[PERSISTENT_LOGIN_DEBUG] app.py routing: is_logged_in() result = {is_logged_in()}")

if is_logged_in():
    print("[PERSISTENT_LOGIN_DEBUG] app.py routing: screen rendered = MAIN APP (Dashboard)")
    render_main_app()
else:
    print("[PERSISTENT_LOGIN_DEBUG] app.py routing: screen rendered = LOGIN/SIGNUP")
    render_login_signup_screen()

_sync_persistent_session_cookie()
