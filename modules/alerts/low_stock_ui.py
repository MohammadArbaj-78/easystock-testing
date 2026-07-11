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

from modules.alerts import low_stock_service
from config.alert_theme import render_alert_banner
from core.session import get_current_store_id

FILTER_OPTION_ALL = "All"


def render_low_stock_alerts_page() -> None:
    """Render the Low Stock Alerts screen."""
    st.subheader("📦 Low Stock Alerts")

    store_id = get_current_store_id()
    counts = low_stock_service.get_low_stock_counts(store_id)

    if counts["total"] == 0:
        st.success("All products are sufficiently stocked. Nothing to reorder right now.")
        return

    selected_severity = _render_filter_dropdown(counts)
    search_term = st.text_input(
        "Search by medicine name or batch number",
        placeholder="e.g. Paracetamol or B001",
    )

    buckets = low_stock_service.get_low_stock_alerts(store_id, search_term=search_term)

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
            effective_threshold.
        severity: One of low_stock_service.SEVERITY_* constants.
    """
    color = low_stock_service.SEVERITY_DISPLAY[severity]["color"]
    qty = product["quantity"]
    threshold = product["effective_threshold"]

    message = (
        f"{product['name']} &nbsp;•&nbsp; "
        f"Batch: {product['batch_number']} &nbsp;•&nbsp; "
        f"Qty: {qty} / Min: {threshold}"
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
