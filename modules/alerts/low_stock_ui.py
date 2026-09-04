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

import streamlit as st
import streamlit.components.v1 as components

from modules.alerts import low_stock_service
from config.alert_theme import render_alert_banner
from core.session import get_current_store_id
from config.settings import DEFAULT_LOW_STOCK_THRESHOLD

FILTER_OPTION_ALL = "All"
GLOBAL_MINIMUM_OPTIONS = list(range(1, 11))  # Requirement 5: strictly 1-10

# Browser-level persistence (localStorage) for the global minimum
# selection, so it survives a full browser close/reopen - distinct
# key/param names from the Auth restoration bridge in app.py
# (LOCALSTORAGE_REFRESH_TOKEN_KEY / "rt"), scoped entirely to this file.
# Per-browser only, not per-account - see render_low_stock_alerts_page()'s
# docstring.
_LOCALSTORAGE_LOW_STOCK_MINIMUM_KEY = "easystock_low_stock_minimum"
_QUERY_PARAM_LOW_STOCK_MINIMUM = "lsm"


def render_low_stock_alerts_page() -> None:
    """Render the Low Stock Alerts screen.

    Browser-level persistence: the global minimum selection is restored
    from localStorage on a genuinely fresh connection (browser closed
    and reopened) via the same script-injection bridge technique
    already proven for Supabase Auth restoration in app.py - a
    sandboxed components.html() iframe cannot navigate the top-level
    window directly, so a small <script> is injected into
    window.parent.document instead, which then executes as the
    parent's own (unsandboxed) script. Uses entirely distinct
    localStorage/query-param names from the Auth bridge, and only ever
    runs while already logged in (this page is only reachable inside
    render_main_app()), so it can never race with app.py's own
    restoration flow. This is per-browser persistence only - the same
    account on a different browser/device will not see this value; see
    the investigation this was based on for that distinction.
    """
    st.subheader("📦 Low Stock Alerts")

    store_id = get_current_store_id()

    if "low_stock_global_minimum_value" not in st.session_state:
        restored_param = st.query_params.get(_QUERY_PARAM_LOW_STOCK_MINIMUM)
        if restored_param is not None:
            try:
                st.session_state["low_stock_global_minimum_value"] = int(restored_param)
            except (TypeError, ValueError):
                pass
            del st.query_params[_QUERY_PARAM_LOW_STOCK_MINIMUM]
        else:
            components.html(
                f"""
                <script>
                try {{
                    var saved = localStorage.getItem({_LOCALSTORAGE_LOW_STOCK_MINIMUM_KEY!r});
                    var params = new URLSearchParams(window.parent.location.search);
                    if (saved && !params.has({_QUERY_PARAM_LOW_STOCK_MINIMUM!r})) {{
                        params.set({_QUERY_PARAM_LOW_STOCK_MINIMUM!r}, saved);
                        var newSearch = params.toString();
                        var bridge = window.parent.document.createElement("script");
                        bridge.textContent = "window.location.search = " + JSON.stringify(newSearch) + ";";
                        window.parent.document.body.appendChild(bridge);
                    }}
                }} catch (e) {{
                    // No saved value, or localStorage unavailable - the
                    // existing DEFAULT_LOW_STOCK_THRESHOLD applies below,
                    // exactly as before this feature.
                }}
                </script>
                """,
                height=0,
            )

    # Requirement 5: session-only (not persisted to the database - see
    # the investigation's recommendation), defaulting to the existing
    # DEFAULT_LOW_STOCK_THRESHOLD so a store that never touches this
    # dropdown sees identical behavior to before this feature existed.
    # A product's own custom minimum_stock_threshold still always wins
    # over this - unchanged, enforced entirely inside
    # products_repository's existing COALESCE/effective-threshold logic.
    global_minimum = st.session_state.get(
        "low_stock_global_minimum_value", DEFAULT_LOW_STOCK_THRESHOLD
    )

    counts = low_stock_service.get_low_stock_counts(store_id, global_minimum=global_minimum)

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
    with filter_col:
        selected_severity = _render_filter_dropdown(counts)
    with minimum_col:
        global_minimum = _render_global_minimum_dropdown()

    search_term = st.text_input(
        "Search by medicine name or batch number",
        placeholder="e.g. Paracetamol or B001",
        key="low_stock_search_term",
    )

    buckets = low_stock_service.get_low_stock_alerts(
        store_id, search_term=search_term, global_minimum=global_minimum
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

    for severity in low_stock_service.ALL_SEVERITIES:
        if buckets[severity]:
            _render_severity_section(severity, buckets[severity])


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
    current = st.session_state.get("low_stock_global_minimum_value", DEFAULT_LOW_STOCK_THRESHOLD)
    index = GLOBAL_MINIMUM_OPTIONS.index(current) if current in GLOBAL_MINIMUM_OPTIONS else 0
    selected = st.selectbox(
        "Minimum stock limit",
        GLOBAL_MINIMUM_OPTIONS,
        index=index,
        key="low_stock_global_minimum_widget",
    )
    st.session_state["low_stock_global_minimum_value"] = selected

    components.html(
        f"""
        <script>
        try {{ localStorage.setItem({_LOCALSTORAGE_LOW_STOCK_MINIMUM_KEY!r}, {selected!r}); }}
        catch (e) {{ /* best-effort, same as the Auth refresh-token persistence */ }}
        </script>
        """,
        height=0,
    )

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


def _render_severity_section(severity: str, products: list) -> None:
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
        f"{display['icon']} {display['label']} ({len(products)})</h4>",
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
