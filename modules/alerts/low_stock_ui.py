"""
Low Stock Alerts screen UI.

Renders three severity-coded sections (Out of Stock = Red, Very Low =
Orange, Low = Yellow) with a filter dropdown and search box. Each
product row shows its current quantity and the effective threshold it
was compared against, so a store owner knows exactly how far below
the reorder point each item is.

No business logic, no SQL - calls modules.alerts.low_stock_service and
renders results. If a product appears in the wrong severity or counts
look wrong, the bug is in low_stock_service.py or the products
repository, never here.
"""

import html

import streamlit as st

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

def render_low_stock_alerts_page() -> None:
    """Render the Low Stock Alerts screen."""
    st.subheader("📦 Low Stock Alerts")

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

    # Requirement 5: session-only (not persisted to the database - see
    # the investigation's recommendation), defaulting to the existing
    # DEFAULT_LOW_STOCK_THRESHOLD so a store that never touches this
    # dropdown sees identical behavior to before this feature existed.
    # A product's own custom minimum_stock_threshold still always wins
    # over this - unchanged, enforced entirely inside
    # products_repository's existing COALESCE/effective-threshold logic.
    
    global_minimum = get_current_low_stock_minimum()

    counts = _get_low_stock_counts_cached(store_id, global_minimum, get_cache_epoch(store_id))

    if counts["total"] == 0:
        st.success("All products are sufficiently stocked. Nothing to reorder right now.")
        # The dropdown is still rendered below the empty-state message in
        # every other branch of this function; here there's nothing to
        # filter yet, so - matching the existing early-return for "no
        # results at all" - the page stops here, same as before this
        # feature (this early return already existed; only the
        # get_low_stock_counts() call above it now takes global_minimum).
        _render_global_minimum_dropdown()
        return

    filter_col, minimum_col = st.columns(2)
    with minimum_col:
        global_minimum = _render_global_minimum_dropdown()

    # Recompute with the JUST-selected minimum, before building the
    # filter dropdown's per-severity numbers - otherwise those numbers
    # would still reflect the PREVIOUS minimum for one extra render
    # (the exact bug this fixes).
    counts = _get_low_stock_counts_cached(store_id, global_minimum, get_cache_epoch(store_id))

    with filter_col:
        selected_severity = _render_filter_dropdown(counts)

    search_col, search_btn_col = st.columns([6, 1.3])

    with search_col:
        search_term = st.text_input(
            "Search by medicine name or batch number",
            placeholder="e.g. Paracetamol or B001",
            key="low_stock_search_term",
        )
    
    with search_btn_col:
        st.button(
            "🔎 Search",
            key="low_stock_search_button",
            type="primary",
            use_container_width=True,
        )
    
    buckets = _get_low_stock_alerts_cached(
        store_id,
        search_term,
        global_minimum,
        get_cache_epoch(store_id),
    )

    # Apply severity filter after fetching (search is applied inside
    # get_low_stock_alerts; severity filter is applied here since it's
    # a pure display concern, not worth a second DB call).
    if selected_severity:
        buckets = {
            k: (v if k == selected_severity else [])
            for k, v in buckets.items()
        }

    total_visible = sum(len(v) for v in buckets.values())
    if total_visible == 0:
        st.info("No products match the current filter/search.")
        return

    # A new search / severity filter / minimum starts again from page 1.
    signature = (search_term, selected_severity, global_minimum)
    if st.session_state.get("low_stock_last_signature") != signature:
        st.session_state["low_stock_last_signature"] = signature
        st.session_state["low_stock_visible_limit"] = LOW_STOCK_PAGE_SIZE
    limit = st.session_state.get("low_stock_visible_limit", LOW_STOCK_PAGE_SIZE)

    remaining = limit
    for severity in low_stock_service.ALL_SEVERITIES:
        if buckets[severity] and remaining > 0:
            shown = buckets[severity][:remaining]
            _render_severity_section(severity, shown, len(buckets[severity]))
            remaining -= len(shown)

    if total_visible > limit:
        st.caption(f"Showing {limit} of {total_visible}")
        st.button(
            f"⬇️ Load {min(LOW_STOCK_PAGE_SIZE, total_visible - limit)} more",
            key="low_stock_load_more",
            use_container_width=True,
            on_click=_load_more_low_stock,
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


def _render_filter_dropdown(counts: dict) -> str | None:
    """Render the severity filter dropdown with live counts.

    Args:
        counts: Output of low_stock_service.get_low_stock_counts().

    Returns:
        The selected SEVERITY_* constant, or None for "All".
    """
    options = [FILTER_OPTION_ALL]
    option_to_severity = {FILTER_OPTION_ALL: None}

    for severity in low_stock_service.ALL_SEVERITIES:
        display = low_stock_service.SEVERITY_DISPLAY[severity]
        label = f"{display['icon']} {display['label']} ({counts[severity]})"
        options.append(label)
        option_to_severity[label] = severity

    selected_label = st.selectbox("Filter by severity", options)
    return option_to_severity[selected_label]


def _render_severity_section(severity: str, products: list, total_count: int = None) -> None:
    """Render one severity section: a colored header and one banner
    row per product.

    Args:
        severity: One of low_stock_service.SEVERITY_* constants.
        products: Products in this severity tier.
    """
    display = low_stock_service.SEVERITY_DISPLAY[severity]

    # Colored section header, same pattern as Expiry Alerts, using the
    # same color values as SEVERITY_DISPLAY (which deliberately mirrors
    # Expiry Alerts' red/orange/yellow palette for visual consistency).
    st.markdown(
        f"<h4 style='color:{display['color']}; margin-bottom:0.2rem;'>"
        f"{display['icon']} {display['label']} "
        f"({total_count if total_count is not None else len(products)})</h4>",
        unsafe_allow_html=True,
    )

    for product in products:
        _render_low_stock_row(product, severity)

    st.write("")


def _render_low_stock_row(product: dict, severity: str) -> None:
    """Render a single low-stock product row showing name, batch,
    current quantity, and the effective threshold - so the store owner
    can see both how low stock is and what the reorder trigger is.

    Uses render_alert_banner from config.alert_theme for structural
    consistency with the Expiry Alerts rows and the Dashboard warning
    card. The color comes from SEVERITY_DISPLAY (not from alert_theme's
    ALERT_TYPE_DISPLAY) because low-stock severity tiers are a distinct
    concept from expiry urgency windows - they just happen to share the
    same red/orange/yellow palette by design choice.

    Args:
        product: Dict with name, batch_number, quantity,
            effective_threshold, mrp, rate.
        severity: One of low_stock_service.SEVERITY_* constants.
    """
    color = low_stock_service.SEVERITY_DISPLAY[severity]["color"]
    qty = product["quantity"]
    threshold = product["effective_threshold"]

    message = (
        f"{product['name']} &nbsp;•&nbsp; "
        f"Batch: {product['batch_number']} &nbsp;•&nbsp; "
        f"Qty: {qty} / Min: {threshold} &nbsp;•&nbsp; "
        f"MRP: {product.get('mrp')} &nbsp;•&nbsp; "
        f"Rate: {product.get('rate')}"
    )

    # render_alert_banner takes an alert_type key from alert_theme's
    # ALERT_TYPE_DISPLAY - but low-stock severity keys are different
    # ("critical", "warning", "low") from expiry alert keys ("expired",
    # "7_days", etc.). So we build the HTML directly here rather than
    # shoehorning severity keys into alert_theme's expiry-specific dict.
    # The visual structure is identical (same border/padding/radius).
    st.markdown(
        f"<div style='border-left: 4px solid {color}; padding: 0.5rem 1rem; "
        f"margin: 0.4rem 0; background-color: rgba(0,0,0,0.02); "
        f"border-radius: 4px;'>"
        f"🔹 <strong>{message}</strong>"
        f"</div>",
        unsafe_allow_html=True,
    )
