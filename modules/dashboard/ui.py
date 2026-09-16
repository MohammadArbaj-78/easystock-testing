"""
Dashboard screen UI.

Renders the four headline inventory metrics as large, clearly-labeled
cards - consistent with the project's UI rule of large buttons/numbers
and minimal clicks, since the target user often checks this screen in a
few seconds between customers rather than doing a detailed review.

Contains no business logic - it calls modules.dashboard.service for
numbers and renders them. If a metric card's number looks wrong, the
bug is in service.py or repository.py, never in this file.
"""

import streamlit as st

from modules.dashboard.service import get_dashboard_metrics
from modules.alerts import service as alerts_service
from config.alert_theme import render_alert_banner
from core.session import get_current_store_id
from core.cache_utils import get_cache_epoch


@st.cache_data(ttl=1, show_spinner=False)
def _get_dashboard_metrics_cached(store_id: int, _epoch: int) -> dict:
    return get_dashboard_metrics(store_id)

def render_dashboard() -> None:
    """Render the Dashboard screen for the currently logged-in store."""
    st.subheader("📊 Dashboard")

    store_id = get_current_store_id()
    metrics = _get_dashboard_metrics_cached(store_id, get_cache_epoch())

    if metrics["total_products"] == 0:
        st.info(
            "No products yet. Once you add products, your inventory "
            "summary will appear here."
        )
        return

    _render_metric_cards(metrics)
    _render_expiring_soon_warning(store_id)
    st.divider()
    _render_detail_sections(metrics)

@st.cache_data(ttl=1, show_spinner=False)
def _get_alert_counts_cached(store_id: int, _epoch: int) -> dict:
    return alerts_service.get_alert_counts(store_id)

def _render_expiring_soon_warning(store_id: int) -> None:
    """Show a single color-coded warning card for the most urgent
    non-empty expiry bucket, mirroring the existing Low Stock warning
    card's placement and tone.

    Reuses modules.alerts.service.get_alert_counts() for bucket counts,
    and config.alert_theme.render_alert_banner() for the HTML card -
    the same function Expiry Alerts uses for its product rows, so both
    pages are guaranteed to look and feel identical.
    """
    counts = _get_alert_counts_cached(store_id, get_cache_epoch())
    
    if counts.get(alerts_service.ALERT_TYPE_15_DAYS, 0) > 0:
        alert_type = alerts_service.ALERT_TYPE_15_DAYS
        message = f"{counts[alert_type]} product(s) expiring within 15 days — action needed soon."
    elif counts.get(alerts_service.ALERT_TYPE_30_DAYS, 0) > 0:
        alert_type = alerts_service.ALERT_TYPE_30_DAYS
        message = f"{counts[alert_type]} product(s) expiring within 30 days."
    elif counts.get(alerts_service.ALERT_TYPE_60_DAYS, 0) > 0:
        alert_type = alerts_service.ALERT_TYPE_60_DAYS
        message = f"{counts[alert_type]} product(s) expiring within 60 days."
    else:
        return

    st.markdown(render_alert_banner(message, alert_type), unsafe_allow_html=True)


def _render_metric_cards(metrics: dict) -> None:
    """Render the four top-level numbers as a 2x2 grid of metric cards.

    A 2x2 grid (rather than 4-across) is deliberate: on a phone screen,
    four columns side by side would force tiny text, working against the
    "readable fonts, mobile-friendly" UI rule. Two columns keep each
    number large and legible on a small screen.
    """
    row1_col1, row1_col2 = st.columns(2)
    row2_col1, row2_col2 = st.columns(2)

    with row1_col1:
        st.metric("Total Products", metrics["total_products"])

    with row1_col2:
        st.metric(
            "Expiring Soon",
            metrics["expiring_soon_count"],
            help="Products expiring within 30 days",
        )

    with row2_col1:
        # delta_color="inverse" renders the expired count in red/warning
        # styling rather than Streamlit's default green-for-positive,
        # since a high expired count is bad news, not good news.
        st.metric(
            "Expired Products",
            metrics["expired_count"],
            delta=("Action needed" if metrics["expired_count"] > 0 else None),
            delta_color="inverse",
        )

    with row2_col2:
        st.metric(
            "Low Stock",
            metrics["low_stock_count"],
            delta=("Reorder soon" if metrics["low_stock_count"] > 0 else None),
            delta_color="inverse",
        )


def _render_detail_sections(metrics: dict) -> None:
    """Render expandable detail lists for each metric that has items
    needing attention.

    Expanders are used instead of always-visible tables so the screen
    stays simple by default (matching "minimal clicks, simple") while
    still letting an owner tap in for specifics when a number looks
    concerning.
    """
    if metrics["expired_count"] > 0:
        with st.expander(f"🔴 {metrics['expired_count']} Expired Product(s)"):
            _render_item_table(metrics["expired_items"])

    if metrics["expiring_soon_count"] > 0:
        with st.expander(f"🟡 {metrics['expiring_soon_count']} Expiring Soon"):
            _render_item_table(metrics["expiring_soon_items"])

    if metrics["low_stock_count"] > 0:
        with st.expander(f"🟠 {metrics['low_stock_count']} Low Stock Product(s)"):
            for item in metrics["low_stock_items"]:
                st.write(
                    f"**{item['name']}** (Batch: {item['batch_number']}) - "
                    f"Qty: {item['quantity']} / Threshold: {item['effective_threshold']} - "
                    f"MRP: {item.get('mrp')} - Rate: {item.get('rate')}"
                )


def _render_item_table(items: list) -> None:
    """Render a simple list of products with name, batch, expiry, and
    price info.

    Args:
        items: List of product dicts with name, batch_number,
            expiry_date, quantity, mrp, rate keys.
    """
    for item in items:
        st.write(
            f"**{item['name']}** (Batch: {item['batch_number']}) - "
            f"Expires: {item['expiry_date']} - Qty: {item['quantity']} - "
            f"MRP: {item.get('mrp')} - Rate: {item.get('rate')}"
        )
