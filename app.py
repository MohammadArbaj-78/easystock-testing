"""
EasyStock - main application entry point.

This file's only responsibility is routing: initialize the database once,
check whether a store is logged in, and show either the login/signup
screen or the main app shell. It deliberately contains no business logic
and no direct database access - if this file starts growing beyond
routing, that's a sign logic is leaking into the wrong layer.
"""

import streamlit as st
import streamlit.components.v1 as components

from config.settings import APP_NAME, LOCALSTORAGE_REFRESH_TOKEN_KEY
from core.database import initialize_database
from core.session import (
    is_logged_in, get_current_store_name, get_current_owner_name,
    get_current_access_token, get_current_refresh_token, start_session, end_session,
)
from core.supabase_auth import sign_out, restore_session
from core.exceptions import SupabaseAuthError, SupabaseConfigError
from core.login_ui import (
    render_login_signup_screen,
    _persist_refresh_token_to_browser,
)
from modules.dashboard.ui import render_dashboard
from modules.products.ui import render_products_page
from modules.alerts.ui import render_expiry_alerts_page
from modules.alerts.low_stock_ui import render_low_stock_alerts_page
from modules.invoice_scan.upload_ui import render_invoice_scan_page
from modules.invoice_scan import review_service
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
            # Stabilization fix (P0): logout must destroy ALL review
            # state, not just the auth session - review data belongs
            # only to a logged-in store's Invoice Scan screen, and must
            # never survive into whatever the next login sees. Safe to
            # call unconditionally even if no review session exists
            # (review_service.clear_session() is a no-op in that case).
            # This is safe to run in the SAME script run that also
            # calls end_session(): after end_session(), is_logged_in()
            # becomes False, so app.py routes to the login screen this
            # rerun - the Invoice Scan page (and its file_uploader
            # widget) is never instantiated this run, so clear_session()
            # resetting that widget key here cannot conflict with it.
            review_service.clear_session()
            # Migration: logout must explicitly end the Supabase Auth
            # session too, not just this app's own st.session_state -
            # otherwise a stale Supabase session could still be sitting
            # in the Supabase client's own memory after this app
            # considers the user logged out. Read before end_session()
            # clears it; sign_out() itself never raises (see its own
            # docstring), so this can never block logout from
            # completing.
            sign_out(get_current_access_token())
            end_session()
            # Requirement 2: also clear the persisted refresh token from
            # the browser's localStorage - otherwise the startup-
            # restoration block below would silently log the user back
            # in on their very next visit, defeating an explicit logout.
            _clear_persisted_refresh_token()
            st.rerun()

        _render_mobile_sidebar_css()
        _render_mobile_sidebar_autoclose(selected_page)

    # Final stabilization fix: the v2.13.4 "isolation" guard that used to
    # sit here (clearing the review session on every navigation away from
    # Invoice Scan) has been REMOVED. It is explicitly no longer wanted:
    # the review must now survive page navigation and remain available
    # until the user clicks "Clear Review" or uploads a genuinely new
    # (different-hash) invoice - navigation alone must never clear it.
    # Logout above still calls review_service.clear_session() - that is
    # a deliberate, separate teardown (a fresh login must never see a
    # previous session's leftover review) and is unaffected by this
    # change. SHA-256 caching in upload_ui.py is untouched either way.

    st.title(f"📦 {APP_NAME}")
    # Leaving Products / Low Stock puts each back on its first page
    # (20 / 25 rows) the next time it is opened, instead of keeping the
    # "Load more" size from the previous visit.
    page_function = NAV_PAGES[selected_page]
    if page_function is not render_products_page:
        for key in ("products_visible_limit", "products_last_search"):
            st.session_state.pop(key, None)
    if page_function is not render_low_stock_alerts_page:
        for key in ("low_stock_visible_limit", "low_stock_last_signature"):
            st.session_state.pop(key, None)
    
    if page_function is not render_sales_page:
        st.session_state.pop("sales_history_visible_limit", None)

    page_function()


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


def _render_mobile_sidebar_autoclose(current_page: str) -> None:
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
        f"""
        <script>
        // current page: {current_page}
        (function() {{
            try {{
                var doc = window.parent.document;
                var STORAGE_KEY = "easystock_last_nav_selection";

                function getSelectedLabel() {{
                    var checked = doc.querySelector(
                        '[data-testid="stSidebar"] [role="radiogroup"] input:checked'
                    );
                    if (!checked) return null;
                    var label = checked.closest('label');
                    return label ? label.innerText.trim() : null;
                }}

                function collapseSidebarIfMobile() {{
                    if (window.parent.innerWidth > 768) return;
                    var selectors = [
                        '[data-testid="stSidebarCollapseButton"] button',
                        '[data-testid="stSidebarCollapseButton"]',
                        '[data-testid="stSidebar"] button[kind="header"]'
                    ];
                    for (var i = 0; i < selectors.length; i++) {{
                        var el = doc.querySelector(selectors[i]);
                        if (el) {{ el.click(); break; }}
                    }}
                }}

                var current = {current_page!r};
                var last = window.parent.sessionStorage.getItem(STORAGE_KEY);
                if (last && current !== last) {{
                    collapseSidebarIfMobile();
                }}
                window.parent.sessionStorage.setItem(STORAGE_KEY, current);
            }} catch (e) {{
                // Fail silently - this is a best-effort mobile enhancement
                // and must never break navigation if it can't run.
            }}
        }})();
        </script>
        """,
        height=0,
    )


def _clear_persisted_refresh_token() -> None:
    """Clear the browser's persisted Supabase refresh token
    (Requirement 2), called on explicit Logout so a stale token can
    never silently re-authenticate the user on their next visit.
    """
    components.html(
        f"""
        <script>
        try {{
            localStorage.removeItem({LOCALSTORAGE_REFRESH_TOKEN_KEY!r});
        }} catch (e) {{ /* best-effort - logout already succeeded either way */ }}
        </script>
        """,
        height=0,
    )


def _clear_persisted_refresh_token_if_unchanged(token_param: str) -> None:
    """Clear the browser's persisted refresh token ONLY if it still
    matches the exact token that just failed to restore - so a
    genuinely dead token gets cleaned up (preventing it from
    repeatedly interfering with fresh logins), while a token a
    concurrent, successful restore has since overwritten with
    something newer is left untouched.
    """
    components.html(
        f"""
        <script>
        try {{
            if (localStorage.getItem({LOCALSTORAGE_REFRESH_TOKEN_KEY!r}) === {token_param!r}) {{
                localStorage.removeItem({LOCALSTORAGE_REFRESH_TOKEN_KEY!r});
            }}
        }} catch (e) {{ /* best-effort */ }}
        </script>
        """,
        height=0,
    )

def _is_temporary_network_error(error: Exception) -> bool:
    """True if a restore failure looks like a temporary network/server
    problem (timeout, connection error) rather than a rejected token.
    """
    text = str(error).lower()
    return any(
        word in text
        for word in ("timed out", "timeout", "could not reach", "connection", "network", "temporarily")
    )

def _attempt_session_restoration() -> None:
    """Requirement 2: on a fresh Streamlit connection (a full browser
    close/reopen, not just a rerun/navigation - those already work via
    st.session_state and never reach this function, since is_logged_in()
    is already True for them) with no active session, check whether the
    browser has a previously-saved Supabase refresh token and, if so,
    silently restore the session instead of showing the login screen.

    Mechanism: st.query_params is the only way this Python code can
    receive a value the browser's own localStorage holds (a plain
    components.html() call is one-way, Python -> browser only) - so a
    tiny JS snippet checks localStorage and, if a token is found,
    redirects the browser to the same URL with that token appended as
    a query parameter, triggering one fresh page load Python CAN read.
    That redirect is only attempted when no such query parameter is
    already present, so this cannot loop: either restoration succeeds
    (session starts, query param cleared, normal app renders) or it
    fails (the query param is cleared AND the stale localStorage token
    is cleared below), and either way the next load has nothing left to
    retry.

    The redirect itself cannot be triggered directly from this
    component's own script: components.html() renders inside a
    sandboxed iframe (allow-scripts + allow-same-origin, but no
    allow-top-navigation/-by-user-activation), and browsers explicitly
    block a sandboxed frame from navigating the top-level window - this
    silently broke restoration before (confirmed with real-browser
    testing; the browser logs a console security warning, not a
    catchable JS exception, so the surrounding try/catch below never
    saw it). The fix: instead of navigating window.parent directly,
    the script below injects a small <script> element into
    window.parent.document itself - because allow-same-origin permits
    full DOM access to the parent document, and a script that executes
    as part of the PARENT's own document (rather than originating from
    the sandboxed iframe) is not subject to the top-navigation
    restriction. Verified with a real headless-Chromium reproduction
    against the exact same sandbox attributes before this change.

    The token appears in the URL for exactly one redirect, is read once,
    and is cleared immediately after - it is never logged, never stored
    anywhere else, and this function returns normally (falling through
    to the login screen) on any failure, since an invalid/expired
    stored token must never crash the app.
    """
    token_param = st.query_params.get("rt")

    if token_param:
        # A restoration attempt is already in flight - try it once, then
        # clear the query param either way so this can never loop.
        try:
            store = restore_session(token_param)
            start_session(
                store_id=store["store_id"],
                store_name=store["store_name"],
                owner_name=store["owner_name"],
                access_token=store["access_token"],
                refresh_token=store["refresh_token"],
                low_stock_minimum=store["low_stock_minimum"],
            )
            _persist_refresh_token_to_browser(store["refresh_token"])
            st.query_params.clear()
            st.rerun()
        except (SupabaseAuthError, SupabaseConfigError) as error:
            st.query_params.clear()
            # Only delete the saved token when Supabase actually rejected
            # it. A timeout says nothing about the token, so keep it and
            # the next page refresh simply tries again.
            if not (isinstance(error, SupabaseConfigError) or _is_temporary_network_error(error)):
                _clear_persisted_refresh_token_if_unchanged(token_param)
        return

    # No restoration in flight yet - ask the browser whether it has a
    # saved token at all, only once per fresh page load.
    components.html(
        f"""
        <script>
        try {{
            var token = localStorage.getItem({LOCALSTORAGE_REFRESH_TOKEN_KEY!r});
            var params = new URLSearchParams(window.parent.location.search);
            if (token && !params.has("rt")) {{
                params.set("rt", token);
                var newSearch = params.toString();
                // Cannot navigate window.parent directly from inside this
                // sandboxed iframe (see docstring above) - inject a
                // <script> into the parent document instead, so the
                // navigation runs as the parent's own, unsandboxed script.
                var bridge = window.parent.document.createElement("script");
                bridge.textContent = "window.location.search = " + JSON.stringify(newSearch) + ";";
                window.parent.document.body.appendChild(bridge);
            }}
        }} catch (e) {{
            // localStorage unavailable, or no token saved - fall through
            // to the normal login screen, exactly as before this feature.
        }}
        </script>
        """,
        height=0,
    )


if is_logged_in():
    # Supabase rotates the refresh token every time it is used, so the
    # copy in the browser must always be the CURRENT one. Writing it
    # here (once per new token, after any login/restore rerun has
    # finished) guarantees it lands.
    _current_refresh_token = get_current_refresh_token()
    if _current_refresh_token and st.session_state.get("_persisted_refresh_token") != _current_refresh_token:
        _persist_refresh_token_to_browser(_current_refresh_token)
        st.session_state["_persisted_refresh_token"] = _current_refresh_token
    render_main_app()
else:
    _attempt_session_restoration()
    render_login_signup_screen()
