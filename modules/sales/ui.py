"""
Sales screen UI.

Renders the Sales page: a live search to find a product to sell, a
compact [-] quantity [+] stepper and Sell button per result, and a
read-only Sales History section below.

Deliberately reuses patterns already established elsewhere in
EasyStock rather than inventing new ones:
  - Live search with the same label/placeholder style as
    modules/products/ui.py's product list search.
  - A compact "Name • Batch: X • Stock: Y • Expires: Z" summary line
    per result, matching modules/products/ui.py's row-summary format.
  - st.divider() between rows, matching
    modules/invoice_scan/review_ui.py's table row separation.
  - Native st.container(border=True) for the Sales History "cards" -
    a real Streamlit component, not custom HTML/CSS, so this satisfies
    "card layout" and "no CSS unless absolutely necessary" at the same
    time.

No custom CSS anywhere in this file. Unlike the Review & Edit table
(modules/invoice_scan/review_ui.py), which needed a scoped, mobile-only
media-query fix because it renders 7+ text-input columns in one wide
row, nothing here does: the quantity stepper is a handful of narrow
buttons and the history cards stack vertically by nature. Both degrade
to mobile naturally with zero CSS, so none was added - CSS here would
be solving a problem that does not exist on this screen.

Talks to modules.sales.service only - never modules.sales.repository or
modules.products.repository/service directly, matching every other
UI file's own layering rule (UI -> Service -> Repository).
"""

import streamlit as st

from modules.sales import service as sales_service
from core.session import get_current_store_id
from core.exceptions import ValidationError


def render_sales_page() -> None:
    """Render the Sales screen: sell workflow, then Sales History below."""
    st.subheader("🛒 Sales")

    _render_sell_section()
    st.divider()
    _render_sales_history_section()


def _render_sell_section() -> None:
    """Render the live search and per-result sell controls."""
    store_id = get_current_store_id()

    search_term = st.text_input(
        "Search by medicine name or batch number",
        placeholder="e.g. Paracetamol or B001",
        key="sales_search_term",
    )

    if not search_term or not search_term.strip():
        st.info("Start typing a medicine name or batch number.")
        return

    products = sales_service.search_products(store_id, search_term)

    if not products:
        st.info("No products match your search.")
        return

    st.caption(f"{len(products)} product(s)")

    for product in products:
        _render_sale_row(store_id, product)
        st.divider()


def _render_sale_row(store_id: int, product: dict) -> None:
    """Render one sellable product: its summary line, then a compact
    [-] quantity [+] stepper and Sell button.

    The quantity is not a free-typed number input - it's a small
    integer held in session state, keyed by this product's real
    database product_id (a stable identity, never a list position -
    the same rule established for the Review & Edit table applies
    here, and product_id already satisfies it without needing a
    synthetic id).
    """
    product_id = product["product_id"]
    stock = product["quantity"]

    st.markdown(
        f"**{product['name']}**  •  Batch: {product['batch_number']}  •  "
        f"Stock: {stock}  •  Expires: {product['expiry_date']}"
    )

    qty_key = f"sales_qty_{product_id}"
    quantity = st.session_state.get(qty_key, 1)
    # Defensive clamp: stock may have changed (another sale, or a Product
    # Management edit) since this session_state value was last set.
    quantity = max(1, min(quantity, stock)) if stock > 0 else 1
    st.session_state[qty_key] = quantity

    minus_col, qty_col, plus_col, sell_col = st.columns([1, 1, 1, 3])

    with minus_col:
        if st.button("−", key=f"sales_minus_{product_id}", disabled=(quantity <= 1), use_container_width=True):
            st.session_state[qty_key] = quantity - 1
            st.rerun()

    with qty_col:
        st.markdown(f"**{quantity}**")

    with plus_col:
        if st.button("+", key=f"sales_plus_{product_id}", disabled=(quantity >= stock), use_container_width=True):
            st.session_state[qty_key] = quantity + 1
            st.rerun()

    with sell_col:
        if st.button(
            "Sell",
            key=f"sales_sell_{product_id}",
            disabled=(stock == 0),
            use_container_width=True,
            type="primary",
        ):
            try:
                sales_service.sell_product(store_id, product_id, quantity)
                st.session_state[qty_key] = 1
                st.success(f"Sold {quantity} × {product['name']}.")
                st.rerun()
            except ValidationError as error:
                st.error(str(error))


def _render_sales_history_section() -> None:
    """Render the read-only Sales History: latest 100, newest first,
    as native bordered-container cards. No edit, no delete, no
    filters, no pagination.
    """
    store_id = get_current_store_id()

    st.markdown("**🧾 Sales History**")

    sales = sales_service.get_sales_history(store_id)

    if not sales:
        st.info("No sales recorded yet.")
        return

    for sale in sales:
        with st.container(border=True):
            st.markdown(f"**{sale['medicine_name']}**")
            st.caption(
                f"Batch: {sale['batch_number']}  •  "
                f"Sold Qty: {sale['sold_quantity']}  •  "
                f"Sold: {sale['sold_at']}"
            )
