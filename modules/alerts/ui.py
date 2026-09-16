"""
Expiry Alerts screen UI.

Renders four color-coded sections (Expired = Red, 7 Days = Orange,
15 Days = Yellow, 30 Days = Blue), each filterable via a dropdown and
searchable by medicine name or batch number.

Contains no business logic and no SQL - calls modules.alerts.service for
categorized data and renders it. If a product appears in the wrong
bucket or a search doesn't filter correctly, the bug is in service.py,
never here.
"""

import streamlit as st

from modules.alerts import service as alerts_service
from modules.products import service as products_service
from config.alert_theme import ALERT_TYPE_DISPLAY, render_alert_banner
from core.session import get_current_store_id
from core.exceptions import ValidationError
from core.cache_utils import get_cache_epoch, bump_cache_epoch


# Maps the human-readable filter dropdown option back to the
# ALERT_TYPE_* constant the service understands. "All Alerts" has no
# corresponding constant - None means "don't filter by type" to the
# service layer.
FILTER_OPTION_ALL = "All Alerts"


def render_expiry_alerts_page() -> None:
    """Render the Expiry Alerts screen: filter/search controls followed
    by color-coded, expandable product sections.
    """
    st.subheader("⏰ Expiry Alerts")

    store_id = get_current_store_id()

    selected_alert_type = _render_filter_dropdown(store_id)
    search_term = st.text_input(
        "Search by medicine name or batch number",
        placeholder="e.g. Paracetamol or B001",
        key="expiry_alerts_search_term",
    )

    filtered_buckets = _get_filtered_alerts_cached(
        store_id, selected_alert_type, search_term, get_cache_epoch()
    )

    total_matching = sum(len(products) for products in filtered_buckets.values())
    if total_matching == 0:
        if search_term or selected_alert_type:
            st.info("No products match the current filter/search.")
        else:
            st.success("No expiry alerts right now. Everything looks good.")
        return

    for alert_type in alerts_service.ALL_ALERT_TYPES:
        products = filtered_buckets[alert_type]
        if products:
            _render_alert_section(store_id, alert_type, products)


@st.cache_data(ttl=300, show_spinner=False)
def _get_alert_counts_cached(store_id: int, _epoch: int) -> dict:
    return alerts_service.get_alert_counts(store_id)

@st.cache_data(ttl=300, show_spinner=False)
def _get_filtered_alerts_cached(store_id: int, alert_type, search_term: str, _epoch: int) -> dict:
    return alerts_service.get_filtered_alerts(
        store_id, alert_type=alert_type, search_term=search_term
    )

def _render_filter_dropdown(store_id: int) -> str:
    """Render the alert-type filter dropdown, with live counts per
    option so a store owner can see where attention is needed before
    selecting a filter.

    Args:
        store_id: The currently logged-in store's ID.

    Returns:
        The selected ALERT_TYPE_* constant, or None if "All Alerts" is
        selected.
    """
    counts = _get_alert_counts_cached(store_id, get_cache_epoch())

    options = [FILTER_OPTION_ALL]
    option_to_alert_type = {FILTER_OPTION_ALL: None}

    for alert_type in alerts_service.ALL_ALERT_TYPES:
        display = alerts_service.ALERT_TYPE_DISPLAY[alert_type]
        label = f"{display['icon']} {display['label']} ({counts[alert_type]})"
        options.append(label)
        option_to_alert_type[label] = alert_type

    selected_label = st.selectbox("Filter by alert type", options)
    return option_to_alert_type[selected_label]


def _render_alert_section(store_id: int, alert_type: str, products: list) -> None:
    """Render one color-coded section (e.g. all Expired products) as a
    colored header followed by a list of product rows.

    Uses ALERT_TYPE_DISPLAY from config.alert_theme - the single source
    of truth for colors/icons/labels - rather than any locally-defined
    color constant.

    Args:
        store_id: The currently logged-in store's ID.
        alert_type: One of the ALERT_TYPE_* constants.
        products: The list of product dicts in this bucket.
    """
    display = ALERT_TYPE_DISPLAY[alert_type]

    st.markdown(
        f"<h4 style='color:{display['color']}; margin-bottom:0.2rem;'>"
        f"{display['icon']} {display['label']} ({len(products)})</h4>",
        unsafe_allow_html=True,
    )

    for product in products:
        _render_alert_product_row(store_id, product, alert_type)

    st.write("")  # spacing gap between sections


def _render_alert_product_row(store_id: int, product: dict, alert_type: str) -> None:
    """Render a single product as an expander (collapsed by default),
    matching the same click-to-open interaction Product Management uses
    for its own rows: the summary is visible at a glance, and actions
    (here, just "Return Medicine") are hidden until the row is opened.

    Also offers a "Return Medicine" action inside the expander: sets
    this product's stock quantity to 0 (reusing
    products_service.return_medicine(), which itself reuses the
    existing edit_product() update path) for when the owner has
    physically pulled an expired medicine to send back to the
    supplier. The record itself, and every other field, is preserved -
    this only zeroes quantity. Once quantity is 0, the product is
    filtered out of every alert bucket by alerts_service (see
    get_categorized_alerts), so it disappears from this screen on the
    next render - no separate removal step is needed here.

    Args:
        store_id: The currently logged-in store's ID.
        product: Dict with product_id, name, batch_number, expiry_date,
            quantity, mrp, rate.
        alert_type: One of the ALERT_TYPE_* constants.
    """
    summary = (
        f"{product['name']}  •  Batch: {product['batch_number']}  •  "
        f"Expires: {product['expiry_date']}  •  Qty: {product['quantity']}  •  "
        f"MRP: {product['mrp']}  •  Rate: {product['rate']}"
    )

    with st.expander(summary):
        message = (
            f"{product['name']} &nbsp;•&nbsp; "
            f"Batch: {product['batch_number']} &nbsp;•&nbsp; "
            f"Expires: {product['expiry_date']} &nbsp;•&nbsp; "
            f"Qty: {product['quantity']} &nbsp;•&nbsp; "
            f"MRP: {product['mrp']} &nbsp;•&nbsp; "
            f"Rate: {product['rate']}"
        )
        st.markdown(render_alert_banner(message, alert_type), unsafe_allow_html=True)

        if product["quantity"] == 0:
            return

        if st.button(
            "↩️ Return Medicine",
            key=f"return_medicine_{product['product_id']}",
        ):
            try:
                products_service.return_medicine(store_id, product["product_id"])
                bump_cache_epoch()
                st.success(f"'{product['name']}' returned - stock set to 0.")
                st.rerun()
            except ValidationError as error:
                st.error(str(error))
