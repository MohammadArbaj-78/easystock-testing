"""
Low Stock screen UI.

Tabs depend on the Quick Setup switch "Asli qty save karo":
  ON  : Alerts | Diary | Agency   (stock is real, so alerts make sense)
  OFF : Diary | Agency            (stock is not kept, so no alerts)

The Alerts tab shows three severity-coded sections (Out of Stock = Red, Very
Low = Orange, Low = Yellow) as thin white lines with a severity filter and a
search box. Each line shows the current quantity and the effective threshold
it was compared against.

No business logic, no SQL - calls modules.alerts.low_stock_service and
renders results. If a product appears in the wrong severity or counts
look wrong, the bug is in low_stock_service.py or the products
repository, never here.
"""

import html
import time

import streamlit as st
import streamlit.components.v1 as components

from modules.alerts import low_stock_service
from config.alert_theme import render_alert_banner
from core.session import (
    get_current_store_id,
    get_current_low_stock_minimum,
    set_current_low_stock_minimum,
)
from core.supabase_auth import update_store_low_stock_minimum
from config.settings import DEFAULT_LOW_STOCK_THRESHOLD
from core.cache_utils import bump_cache_epoch, get_cache_epoch
from modules.low_stock_diary.agency_tab import render_agency_tab
from modules.low_stock_diary.ui import render_low_stock_diary
from modules.alerts import mode as alerts_mode

try:
    from st_keyup import st_keyup
except ImportError:          # package not installed: a normal text box is used instead
    st_keyup = None

FILTER_OPTION_ALL = "All"
GLOBAL_MINIMUM_OPTIONS = list(range(1, 11))  # Requirement 5: strictly 1-10


LOW_STOCK_PAGE_SIZE = 20


def _load_more_low_stock() -> None:
    st.session_state["low_stock_visible_limit"] = (
        st.session_state.get("low_stock_visible_limit", LOW_STOCK_PAGE_SIZE)
        + LOW_STOCK_PAGE_SIZE
    )

@st.cache_data(show_spinner=False)
def _get_low_stock_counts_cached(store_id: int, global_minimum: int, _epoch: int) -> dict:
    return low_stock_service.get_low_stock_counts(store_id, global_minimum=global_minimum)

@st.cache_data(show_spinner=False)
def _get_low_stock_alerts_cached(store_id: int, search_term: str, global_minimum: int, _epoch: int) -> dict:
    return low_stock_service.get_low_stock_alerts(
        store_id, search_term=search_term, global_minimum=global_minimum
    )

# Swiping on the Low Stock page (2 or 3 tabs):
#   - swipe LEFT (finger from right to left)  -> the next tab,
#   - swipe RIGHT                             -> the previous tab. On the FIRST
#     tab a right swipe opens the sidebar, as everywhere in the app.
#   - a line swiped right inside the Diary / Agency tab is removed (see
#     modules.low_stock_diary.ui); that swipe never opens the sidebar and never
#     changes the tab.
# It only presses a tab's own button, so the tabs behave exactly as Streamlit
# made them. Ignored while the sidebar is open (a left swipe then closes it),
# and when the swipe starts on a text box, slider, table or a sideways-scrolling
# area. The sidebar is kept shut when a tab changes by listening first (capture
# phase) and stopping that one touchend from reaching the sidebar's own
# listener. Installs itself once per browser page; fails silently.
_TAB_SWIPE_JS = """
<script>
(function () {
    try {
        var host = window.parent;
        if (host.__easystockTabSwipeV3) { return; }
        var install = function () {
            if (window.__easystockTabSwipeV3) { return; }
            window.__easystockTabSwipeV3 = true;
            var MIN_DX = 70, RATIO = 2, MAX_MS = 700;
            var NO_SWIPE = 'input, textarea, select, canvas, [contenteditable="true"], ' +
                '[role="slider"], [data-testid="stDataFrame"], [data-testid="stDataEditor"], ' +
                '[data-testid="stSidebar"]';
            function sidebarOpen() {
                var sb = document.querySelector('[data-testid="stSidebar"]');
                if (!sb) { return false; }
                var attr = sb.getAttribute('aria-expanded');
                if (attr !== null) { return attr === 'true'; }
                return sb.getBoundingClientRect().right > 40;
            }
            function startsOnNoSwipe(el) {
                while (el && el !== document.body) {
                    if (el.nodeType === 1) {
                        if (el.matches && el.matches(NO_SWIPE)) { return true; }
                        var cs = window.getComputedStyle(el);
                        if (/(auto|scroll)/.test(cs.overflowX) && el.scrollWidth > el.clientWidth + 1) { return true; }
                    }
                    el = el.parentNode;
                }
                return false;
            }
            // The Low Stock tab bar: the one that has both a Diary and an Agency tab.
            function lowStockTabs() {
                var all = document.querySelectorAll('[role="tab"]');
                for (var i = 0; i < all.length; i++) {
                    if ((all[i].textContent || '').indexOf('Diary') === -1) { continue; }
                    var bar = all[i].parentElement;
                    if (!bar || (bar.textContent || '').indexOf('Agency') === -1) { continue; }
                    return Array.prototype.slice.call(bar.querySelectorAll('[role="tab"]'));
                }
                return null;
            }

            var startX = 0, startY = 0, startT = 0, armed = false, onLine = false;
            document.addEventListener('touchstart', function (e) {
                armed = false;
                if (!e.touches || e.touches.length !== 1) { return; }
                var t = e.touches[0];
                startX = t.clientX; startY = t.clientY; startT = Date.now();
                onLine = !!(e.target.closest && e.target.closest('.lsd-row'));
                armed = !startsOnNoSwipe(e.target);
            }, { passive: true, capture: true });
            document.addEventListener('touchend', function (e) {
                var ok = armed; armed = false;
                if (!ok || !e.changedTouches || !e.changedTouches.length) { return; }
                if (Date.now() - startT > MAX_MS) { return; }
                var t = e.changedTouches[0];
                var dx = t.clientX - startX, dy = t.clientY - startY;
                if (Math.abs(dx) < Math.abs(dy) * RATIO) { return; }
                var tabs = lowStockTabs();
                if (!tabs || tabs.length < 2) { return; }
                if (sidebarOpen()) { return; }
                var index = 0;
                for (var i = 0; i < tabs.length; i++) {
                    if (tabs[i].getAttribute('aria-selected') === 'true') { index = i; }
                }
                if (dx >= 40) {
                    if (onLine) { e.stopPropagation(); return; }          // the line's own slide-to-remove
                    if (index > 0) {                                      // not the first tab: no sidebar here
                        e.stopPropagation();
                        if (dx >= MIN_DX) { tabs[index - 1].click(); }
                    }
                } else if (dx <= -MIN_DX && index < tabs.length - 1) {
                    tabs[index + 1].click();
                }
            }, { passive: false, capture: true });
            document.addEventListener('touchcancel', function () { armed = false; }, { passive: true });
        };
        var bridge = host.document.createElement('script');
        bridge.textContent = '(' + install.toString() + ')();';
        host.document.body.appendChild(bridge);
        host.__easystockTabSwipeV3 = true;
    } catch (e) {
        // best effort - the tabs still work with a tap
    }
})();
</script>
"""


def _inject_tab_swipe() -> None:
    components.html(_TAB_SWIPE_JS, height=0)


# The Quick Setup switch "Asli qty save karo" - see modules/alerts/mode.py.
_REAL_QTY_KEY = alerts_mode.REAL_QTY_KEY


def _alerts_enabled(store_id: int) -> bool:
    """True when the store keeps real quantities: then the Alerts tab shows."""
    return alerts_mode.alerts_enabled(store_id)


def render_low_stock_alerts_page() -> None:
    """The Low Stock screen: Alerts | Diary | Agency, or only Diary | Agency
    when the store does not keep real quantities."""
    st.subheader("📦 Low Stock")
    store_id = get_current_store_id()
    _inject_tab_swipe()
    if _alerts_enabled(store_id):
        alerts_tab, diary_tab, agency_tab = st.tabs(["⚠️ Alerts", "📒 Diary", "🏢 Agency"])
        with alerts_tab:
            _render_alerts_tab()
    else:
        diary_tab, agency_tab = st.tabs(["📒 Diary", "🏢 Agency"])
    with diary_tab:
        render_low_stock_diary()
    with agency_tab:
        render_agency_tab()


def _render_alerts_tab() -> None:
    """The Low Stock Alerts."""
    store_id = get_current_store_id()

    # "Set quantity" mode: the zero stock medicines as +/- blocks. The switch
    # stays ON until it is switched off (also after visiting another page).
    if "low_stock_zero_mode" not in st.session_state:
        st.session_state["low_stock_zero_mode"] = st.session_state.get("low_stock_zero_mode_memory", False)
    zero_mode = st.toggle("✏️ Zero stock medicines ki quantity set karo", key="low_stock_zero_mode")
    st.session_state["low_stock_zero_mode_memory"] = zero_mode
    if zero_mode:
        _render_zero_stock_setter(store_id)
        return
    _render_alerts_list(store_id)


_CSS = """
<style>
.ls-list { display: flex; flex-direction: column; gap: 0.35rem; margin: 0.2rem 0 0.5rem 0; }
.ls-head { font-weight: 700; font-size: 0.9rem; margin: 0.6rem 0 0.1rem 0.1rem; }
.ls-row { display: flex; align-items: center; gap: 0.7rem; background: #fff;
          border: 1px solid rgba(49,51,63,0.12); border-left: 5px solid #ccc; border-radius: 0.6rem;
          padding: 0.45rem 0.75rem; }
.ls-main { flex: 1; min-width: 0; }
.ls-name { font-weight: 600; line-height: 1.3; overflow-wrap: anywhere; }
.ls-sub { font-size: 0.76rem; color: #777; line-height: 1.3; overflow-wrap: anywhere; }
.ls-qty { text-align: right; flex: none; line-height: 1.2; }
.ls-qty b { font-size: 1.15rem; }
.ls-qty small { display: block; font-size: 0.72rem; color: #888; }
</style>
"""


def _search_box() -> str:
    hint = "Dawai ya batch number se dhoondho"
    if st_keyup is not None:
        try:
            text = st_keyup("Search", placeholder=hint, debounce=150, key="low_stock_search_kw",
                            label_visibility="collapsed")
        except TypeError:
            text = st_keyup("Search", debounce=150, key="low_stock_search_kw")
        return (text or "").strip()
    return (st.text_input("Search", placeholder=hint, key="low_stock_search_kw",
                          label_visibility="collapsed") or "").strip()


def _qty_text(value) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _row_html(product: dict, severity: str) -> str:
    color = low_stock_service.SEVERITY_DISPLAY[severity]["color"]
    sub = [f"Batch {product['batch_number']}"] if product.get("batch_number") else []
    for label, key in (("MRP", "mrp"), ("Rate", "rate")):
        value = product.get(key)
        if value not in (None, "", 0, 0.0):
            sub.append(f"{label} ₹{_qty_text(value)}")
    return (
        f"<div class='ls-row' style='border-left-color:{color};'>"
        f"<div class='ls-main'><div class='ls-name'>{html.escape(str(product['name']))}</div>"
        f"<div class='ls-sub'>{html.escape('  •  '.join(sub))}</div></div>"
        f"<div class='ls-qty'><b style='color:{color};'>{html.escape(_qty_text(product['quantity']))}</b>"
        f"<small>Min {html.escape(_qty_text(product['effective_threshold']))}</small></div></div>"
    )


def _section_html(severity: str, products: list, total_count: int) -> str:
    display = low_stock_service.SEVERITY_DISPLAY[severity]
    return (
        f"<div class='ls-head' style='color:{display['color']};'>{display['icon']} {display['label']} • {total_count}</div>"
        "<div class='ls-list'>" + "".join(_row_html(product, severity) for product in products) + "</div>"
    )


@st.fragment
def _render_alerts_list(store_id: int) -> None:
    """A fragment: typing in the search box or tapping a filter redraws only
    this list."""
    st.markdown(_CSS, unsafe_allow_html=True)

    # Session-only minimum (see _render_global_minimum_dropdown); a product's
    # own custom minimum always wins, enforced inside the products repository.
    with st.expander("⚙️ Minimum stock limit"):
        global_minimum = _render_global_minimum_dropdown()

    counts = _get_low_stock_counts_cached(store_id, global_minimum, get_cache_epoch(store_id))
    if counts["total"] == 0:
        st.success("Sab products ka stock theek hai. Abhi kuch mangwana nahi hai.")
        return

    selected_severity = st.pills(
        "Filter", low_stock_service.ALL_SEVERITIES, selection_mode="single",
        format_func=lambda severity: (
            f"{low_stock_service.SEVERITY_DISPLAY[severity]['icon']} "
            f"{low_stock_service.SEVERITY_DISPLAY[severity]['label']} ({counts[severity]})"
        ),
        key="low_stock_severity_pills", label_visibility="collapsed",
    )
    search_term = _search_box()

    buckets = _get_low_stock_alerts_cached(store_id, search_term, global_minimum, get_cache_epoch(store_id))
    if selected_severity:
        buckets = {k: (v if k == selected_severity else []) for k, v in buckets.items()}

    total_visible = sum(len(v) for v in buckets.values())
    if total_visible == 0:
        st.info("Is filter ya search me koi dawai nahi mili.")
        return

    # A new search / severity filter / minimum starts again from page 1.
    signature = (search_term, selected_severity, global_minimum)
    if st.session_state.get("low_stock_last_signature") != signature:
        st.session_state["low_stock_last_signature"] = signature
        st.session_state["low_stock_visible_limit"] = LOW_STOCK_PAGE_SIZE
    limit = st.session_state.get("low_stock_visible_limit", LOW_STOCK_PAGE_SIZE)

    remaining = limit
    parts = []
    for severity in low_stock_service.ALL_SEVERITIES:
        if buckets[severity] and remaining > 0:
            shown = buckets[severity][:remaining]
            parts.append(_section_html(severity, shown, len(buckets[severity])))
            remaining -= len(shown)
    st.markdown("".join(parts), unsafe_allow_html=True)

    if total_visible > limit:
        st.caption(f"{limit} / {total_visible} dikh rahi hain")
        st.button(
            f"⬇️ Aur {min(LOW_STOCK_PAGE_SIZE, total_visible - limit)} dikhao",
            key="low_stock_load_more", use_container_width=True, on_click=_load_more_low_stock,
        )


_ZERO_KEY = "low_stock_zero_state"
_ZERO_PAGE_SIZE = 20


def _zero_state(store_id: int) -> dict:
    """What this screen remembers: the zero stock list (read once), the
    quantities set so far, how many are shown. Reset for another store."""
    epoch = get_cache_epoch(store_id)
    state = st.session_state.get(_ZERO_KEY)
    if state is None or state["store_id"] != store_id or state["epoch"] != epoch:
        kept = state["qty"] if state is not None and state["store_id"] == store_id else {}
        state = {
            "store_id": store_id, "epoch": epoch, "qty": kept, "limit": _ZERO_PAGE_SIZE,
            "rows": low_stock_service.get_zero_stock_medicines(store_id),
        }
        st.session_state[_ZERO_KEY] = state
    return state


def _zero_adjust(product_id: int, delta: int) -> None:
    quantities = st.session_state[_ZERO_KEY]["qty"]
    quantities[product_id] = max(0, quantities.get(product_id, 0) + delta)


def _zero_more() -> None:
    st.session_state[_ZERO_KEY]["limit"] += _ZERO_PAGE_SIZE


def _inject_zero_row_css() -> None:
    """Each medicine block's - / name / + on ONE line (same look as Quick Setup)."""
    st.markdown(
        """
        <style>
        div[class*="st-key-lz_row_"] div[data-testid="stHorizontalBlock"] {
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            gap: 0.4rem !important;
            align-items: center !important;
        }
        div[class*="st-key-lz_row_"] div[data-testid="stColumn"] {
            width: auto !important;
            min-width: 0 !important;
        }
        div[class*="st-key-lz_row_"] div[data-testid="stColumn"]:first-child,
        div[class*="st-key-lz_row_"] div[data-testid="stColumn"]:last-child {
            flex: 0 0 56px !important;
        }
        div[class*="st-key-lz_row_"] div[data-testid="stColumn"]:not(:first-child):not(:last-child) {
            flex: 1 1 auto !important;
        }
        div[class*="st-key-lz_row_"] button[kind="secondary"] {
            aspect-ratio: 1 / 1;
            font-size: 1.4rem;
        }
        div[class*="st-key-lz_row_"] button { touch-action: manipulation; }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.fragment
def _render_zero_stock_setter(store_id: int) -> None:
    """The zero stock medicines as Quick Setup style blocks: set the real
    quantity with - / + and press Save. A fragment, so - / + redraw only this
    part (and read nothing from the database)."""
    _inject_zero_row_css()
    state = _zero_state(store_id)
    rows, quantities = state["rows"], state["qty"]

    flash = st.session_state.pop("low_stock_zero_flash", None)
    if flash:
        st.success(flash)

    chosen = {product_id: qty for product_id, qty in quantities.items() if qty > 0}
    save_col, count_col = st.columns([1, 2])
    with save_col:
        save_clicked = st.button(
            "💾 Save", key="low_stock_zero_save", type="primary",
            use_container_width=True, disabled=not chosen,
        )
    with count_col:
        if chosen:
            st.caption(f"✅ {len(chosen)} medicine(s) ki quantity set • Total qty: {sum(chosen.values()):g}")
        else:
            st.caption("➖ ➕ se sahi quantity set karo, phir Save dabao.")

    if save_clicked and chosen:
        try:
            saved = low_stock_service.set_zero_stock_quantities(store_id, chosen)
        except Exception as error:
            st.error(f"Save nahi ho saka: {error}")
        else:
            bump_cache_epoch(store_id)
            st.session_state[_ZERO_KEY]["qty"] = {}
            st.session_state["low_stock_zero_flash"] = f"✅ {saved} medicine(s) ki quantity save ho gayi."
            st.rerun(scope="fragment")

    st.divider()
    if not rows:
        st.success("Koi bhi medicine 0 stock par nahi hai.")
        return
    for row in rows[: state["limit"]]:
        product_id = row["product_id"]
        mrp = low_stock_service._number(row.get("mrp"))
        mrp_line = (
            f"<div style='font-size:0.75rem; color:#888;'>MRP ₹{mrp:g}</div>" if mrp > 0 else ""
        )
        with st.container(border=True, key=f"lz_row_{product_id}"):
            minus_col, name_col, plus_col = st.columns([1, 3, 1], vertical_alignment="center")
            with minus_col:
                st.button(
                    "➖", key=f"lz_minus_{product_id}", use_container_width=True,
                    on_click=_zero_adjust, args=(product_id, -1),
                )
            with name_col:
                st.markdown(
                    "<div style='text-align:center;'>"
                    f"<div style='font-size:1.05rem; font-weight:600;'>{html.escape(str(row['name']))}</div>"
                    f"{mrp_line}"
                    "<div style='font-size:1.3rem; font-weight:700; margin-top:2px;'>"
                    f"Qty: {quantities.get(product_id, 0):g}</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )
            with plus_col:
                st.button(
                    "➕", key=f"lz_plus_{product_id}", use_container_width=True,
                    on_click=_zero_adjust, args=(product_id, 1),
                )
    if len(rows) > state["limit"]:
        st.caption(f"Showing {state['limit']} of {len(rows)}")
        st.button(
            f"⬇️ Load {min(_ZERO_PAGE_SIZE, len(rows) - state['limit'])} more",
            key="low_stock_zero_more", use_container_width=True, on_click=_zero_more,
        )


def _render_global_minimum_dropdown() -> int:
    """Render the "Minimum Stock Limit" dropdown (Requirement 5) and
    return the currently selected value (1-10).

    Backed by st.session_state (key "low_stock_global_minimum") so the
    selection survives a rerun within the current session (e.g.
    changing the severity filter or typing a search term) without a
    database change - session-only, per the investigation's
    recommendation, since no existing per-store settings storage exists
    to persist this beyond the session without a schema change.

    Changing this dropdown triggers a normal Streamlit rerun (like any
    other widget), which immediately re-fetches low-stock results with
    the new value - no extra plumbing needed for the "refresh
    immediately" requirement.
    """
    current = get_current_low_stock_minimum()
    index = GLOBAL_MINIMUM_OPTIONS.index(current) if current in GLOBAL_MINIMUM_OPTIONS else 0
    selected = st.selectbox(
        "Minimum stock limit",
        GLOBAL_MINIMUM_OPTIONS,
        index=index,
        key="low_stock_global_minimum_widget",
    )
    if selected != current:
        update_store_low_stock_minimum(
            get_current_store_id(),
            selected,
        )
        set_current_low_stock_minimum(selected)
    
    return selected