"""
Sales screen UI.

Renders the Sales page: a live autocomplete search to find a product to
sell (or a "Frequently Sold" shortlist when the search box is empty),
a compact [-] quantity [+] stepper and Sell button for the selected
product, and a read-only Sales History section below.

Search UX (this file's own layer only - the underlying sell mechanics
in _render_sale_row are unchanged and reused as-is):
  - An empty search box never loads the full inventory - it shows a
    prompt plus the Frequently Sold section instead.
  - As the owner types, up to SALES_SEARCH_SUGGESTION_LIMIT lightweight
    suggestions appear (name, batch, stock only - no expiry/MRP/GST),
    each a single compact row (a dropdown-list entry, not a card).
  - Clicking a suggestion or a Frequently Sold tile fills the search
    box, hides the suggestion list, and shows that product's full
    detail (the unmodified per-row sell controls) immediately - the
    owner never has to search again for the same item.

Deliberately reuses patterns already established elsewhere in
EasyStock rather than inventing new ones:
  - Live search with the same label/placeholder style as
    modules/products/ui.py's product list search.
  - A compact "Name • Batch: X • Stock: Y • Expires: Z" summary line
    for the selected product's full detail, matching
    modules/products/ui.py's row-summary format.
  - st.divider() between the sell section and Sales History, matching
    modules/invoice_scan/review_ui.py's table row separation.
  - Native st.container(border=True) for the Sales History cards - a
    real Streamlit component, not custom HTML/CSS. Search suggestions
    and Frequently Sold rows are deliberately NOT cards - they are
    compact, single-row buttons styled as a dropdown list, since a
    bordered card per suggestion wastes vertical space for something
    meant to be scanned quickly.

No custom CSS anywhere in this file. Every element here (suggestion
rows, Frequently Sold rows, Sales History cards) uses only native
Streamlit components - none of them have the Review & Edit table's
wide-multi-column failure mode, so none of them need CSS to work
correctly on mobile; they all stack naturally.

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
    """Render the live search/autocomplete, Frequently Sold, and the
    selected product's full sell controls.

    Flow:
      - A product can be "selected" (session_state key
        sales_selected_product_id) either by clicking a search
        suggestion or a Frequently Sold tile. While a valid selection
        is active, this renders only that product's full detail (via
        the unmodified _render_sale_row) - no suggestion list, no
        Frequently Sold, matching "the owner should not search again".
      - If the search box is empty and nothing is selected: show the
        guidance message and the Frequently Sold section.
      - Otherwise: show up to SALES_SEARCH_SUGGESTION_LIMIT lightweight
        suggestions (name, batch, stock only - no expiry/MRP/GST).
    """
    store_id = get_current_store_id()

    search_term = st.text_input(
        "Search by medicine name or batch number",
        placeholder="e.g. Paracetamol or B001",
        key="sales_search_term",
    )

    selected_product = _get_active_selection(store_id, search_term)
    if selected_product is not None:
        _render_sale_row(store_id, selected_product)
        return

    if not search_term or not search_term.strip():
        st.info("Start typing a medicine name or batch number.")
        _render_frequently_sold(store_id)
        return

    suggestions = sales_service.search_products(store_id, search_term)

    if not suggestions:
        st.info("No products match your search.")
        return

    for product in suggestions:
        _render_suggestion_tile(product)


def _get_active_selection(store_id: int, search_term: str) -> dict:
    """Resolve the currently-selected product, if any, and clear a
    stale selection.

    A selection is only treated as still active if: a product_id is
    recorded, that product still exists and is still in stock, and the
    search box still shows exactly the name that selecting it filled
    in. If the owner has typed something different, the selection is
    dropped and search/autocomplete takes over again on this same
    render - the owner never needs an extra click to "undo" a stale
    selection.
    """
    selected_id = st.session_state.get("sales_selected_product_id")
    if selected_id is None:
        return None

    product = sales_service.get_product(store_id, selected_id)
    if product is not None and product["quantity"] > 0 and search_term == product["name"]:
        return product

    st.session_state.pop("sales_selected_product_id", None)
    return None


def _select_product(product: dict) -> None:
    """on_click callback for a suggestion/Frequently Sold row: fills the
    search box, marks this product selected, and resets its quantity to
    1 - matching "Reset quantity to 1" and "the owner should not search
    again".

    This MUST be wired as a widget's on_click callback, not called from
    inside a plain "if st.button(...):" block. Streamlit callbacks run
    in a dedicated phase before the script body reruns and widgets are
    re-instantiated - so setting st.session_state["sales_search_term"]
    here is always safe. Doing the same assignment from inside the
    normal script body (after the search text_input has already been
    instantiated earlier in that same run) is exactly what raised
    StreamlitAPIException: st.session_state.sales_search_term cannot be
    modified after the widget with key sales_search_term is
    instantiated. No st.rerun() call is needed here either - Streamlit
    already reruns automatically after any widget interaction,
    including a button's on_click callback.
    """
    st.session_state["sales_search_term"] = product["name"]
    st.session_state["sales_selected_product_id"] = product["product_id"]
    st.session_state[f"sales_qty_{product['product_id']}"] = 1


def _render_suggestion_tile(product: dict) -> None:
    """Render one compact, single-row suggestion: name, batch, stock
    only - no expiry, MRP, or GST. A dropdown-style list entry, not a
    bordered card - the whole row is one native st.button (Streamlit
    supports basic Markdown in widget labels, including bold text and
    line breaks), so clicking anywhere on the row selects it via the
    on_click callback above. No separate container, no separate
    "Select" sub-button, minimal vertical spacing.
    """
    label = f"**{product['name']}**\nBatch: {product['batch_number']} • Stock: {product['quantity']}"
    st.button(
        label,
        key=f"sales_select_{product['product_id']}",
        use_container_width=True,
        on_click=_select_product,
        args=(product,),
    )


def _render_frequently_sold(store_id: int) -> None:
    """Render the "⭐ Frequently Sold" section shown when the search box
    is empty: top sellers that are still in stock, each clicking exactly
    like a search suggestion.
    """
    frequently_sold = sales_service.get_frequently_sold(store_id)

    if not frequently_sold:
        return

    st.markdown("**⭐ Frequently Sold**")
    for product in frequently_sold:
        _render_suggestion_tile(product)


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
