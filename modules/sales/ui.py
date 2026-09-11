"""
Sales screen UI.

Renders the Sales page: a live autocomplete search (with a clear
button) to find a product to sell (or a "Frequently Sold" shortlist
when the search box is empty), a compact one-row [-] quantity [+] Sell
control for the selected product, and a read-only Sales History
section below.

Search UX (this file's own layer only - the underlying sell mechanics
in _render_sale_row are unchanged and reused as-is):
  - An empty search box never loads the full inventory - it shows a
    prompt plus the Frequently Sold section instead.
  - A ❌ button next to the search box clears the search text and any
    active selection, returning to the empty-box state (prompt +
    Frequently Sold) without calling any service.
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
  - The quantity stepper + Sell row uses the SAME scoped-CSS pattern
    already established (and documented in AI_RULES.md) for the
    Review & Edit table's mobile layout: flex-wrap: nowrap plus fixed
    per-column pixel widths, scoped via st.container(key=...) so it
    cannot affect st.columns() layouts anywhere else in the app.
    Unlike the Review & Edit table's fix, this one is NOT gated behind
    a mobile-only media query - it applies on every screen size, since
    a compact one-row selector was explicitly wanted on desktop too,
    not only on mobile.

The quantity stepper + Sell row uses one scoped CSS block (unconditional,
both screen sizes - see above). A second, separate CSS block is scoped
to the whole page (st.container(key="sales_page")) and is mobile-only
(@media max-width: 768px): it tightens vertical spacing between
stacked elements, trims Sales History cards' inner padding, and
guards against horizontal overflow/enforces text wrapping - general
mobile polish that doesn't belong to any one control. Desktop is
unaffected by this second block by construction, since it never
applies above that viewport width. Every other element here
(suggestion rows, Frequently Sold rows, the search box) uses only
native Streamlit components - neither CSS block changes their own
internal behavior, only the overall page's spacing/wrapping/overflow
around them.

Talks to modules.sales.service only - never modules.sales.repository or
modules.products.repository/service directly, matching every other
UI file's own layering rule (UI -> Service -> Repository).
"""

import streamlit as st
from datetime import datetime, timezone

from core.cache_utils import get_cache_epoch, bump_cache_epoch
from modules.sales import service as sales_service
from core.session import get_current_store_id
from core.exceptions import ValidationError


def render_sales_page() -> None:
    """Render the Sales screen: sell workflow, then Sales History below."""
    st.subheader("🛒 Sales")

    _render_mobile_layout_css()

    with st.container(key="sales_page"):
        _render_sell_section()
        st.divider()
        _render_sales_history_section()


def _render_mobile_layout_css() -> None:
    """Mobile-only CSS for general page spacing/wrapping/overflow safety.

    Entirely inside @media (max-width: 768px), so desktop is completely
    unaffected - this is the general "keep desktop exactly as it is,
    only touch mobile" pattern already established for the Review &
    Edit table, applied here at the whole-page level rather than to one
    control. It is separate from, and does not touch, the search clear
    button or the quantity stepper + Sell row - both already completed
    and scoped to their own container keys.

    Scoped to st.container(key="sales_page") so nothing here can leak
    into Dashboard, Alerts, Product Management, or Invoice Scan:
      - Tightens the default vertical gap Streamlit puts between
        stacked elements (suggestion rows, Frequently Sold rows, Sales
        History cards) - "remove unnecessary vertical spacing on
        mobile" - without touching any single control's own layout.
      - Trims the default inner padding of bordered containers
        (currently only Sales History cards use st.container(border=
        True)) so they use the available narrow width more efficiently
        - "Sales History cards should use the available width
        properly". Targets Streamlit's own documented bordered-
        container wrapper element; if a future Streamlit version
        renames it, this rule simply matches nothing and has no
        effect - it cannot break anything either way.
      - overflow-x: hidden plus word/overflow-wrap on the whole page
        container is a page-level safety net so long medicine names or
        any other text-heavy element can only wrap, never force
        horizontal overflow - "product information should wrap
        cleanly" and "prevent controls from overflowing on narrow
        screens".
    """
    st.markdown(
        """
        <style>
        @media (max-width: 768px) {
            .st-key-sales_page {
                overflow-x: hidden;
            }
            .st-key-sales_page [data-testid="stVerticalBlock"] {
                gap: 0.4rem !important;
            }
            .st-key-sales_page [data-testid="stVerticalBlockBorderWrapper"] {
                padding: 0.6rem !important;
            }
            .st-key-sales_page p {
                word-wrap: break-word;
                overflow-wrap: break-word;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


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

    search_col, clear_col = st.columns([6, 1])
    with search_col:
        search_term = st.text_input(
            "Search by medicine name or batch number",
            placeholder="e.g. Paracetamol or B001",
            key="sales_search_term",
        )
    with clear_col:
        st.button("❌", key="sales_clear_search", on_click=_clear_search, help="Clear search")

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


def _clear_search() -> None:
    """on_click callback for the search clear (❌) button: resets the
    search box and drops any active selection.

    Must be an on_click callback, not called from inside a plain
    "if st.button(...):" block, for the exact same reason
    _select_product must be - it writes to
    st.session_state["sales_search_term"], which belongs to the
    text_input rendered earlier this run. Doing this write from the
    normal script body would raise the same StreamlitAPIException fixed
    in v2.4.2. Calls no service function - clearing is a pure UI/session
    state reset with nothing to validate, fetch, or persist, so there is
    no unnecessary logic to rerun here.
    """
    st.session_state["sales_search_term"] = ""
    st.session_state.pop("sales_selected_product_id", None)


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


@st.cache_data(ttl=20, show_spinner=False)
def _get_frequently_sold_cached(store_id: int, _epoch: int) -> list:    
    return sales_service.get_frequently_sold(store_id)

def _render_frequently_sold(store_id: int) -> None:
    """Render the "⭐ Frequently Sold" section shown when the search box
    is empty: top sellers that are still in stock, each clicking exactly
    like a search suggestion.
    """
    frequently_sold = _get_frequently_sold_cached(store_id, get_cache_epoch())
    
    if not frequently_sold:
        return

    st.markdown("**⭐ Frequently Sold**")
    for product in frequently_sold:
        _render_suggestion_tile(product)


def _render_qty_sell_row_css() -> None:
    """Scoped CSS so the quantity stepper + Sell button stay one
    compact horizontal row on BOTH desktop and mobile - explicitly
    requested to apply on both, unlike the Review & Edit table's
    mobile-only media-query treatment.

    Native st.columns() alone cannot achieve "always one row": below
    Streamlit's own built-in mobile breakpoint, st.columns() switches
    to vertical stacking regardless of how few or narrow the columns
    are - which is exactly the "stacked -, 1, +, Sell" layout being
    replaced here. Two things are needed together (the same pattern
    already established for the Review & Edit table, reused here
    rather than reinvented): `flex-wrap: nowrap` to override the native
    stacking, and a fixed pixel width per column (with no shrink/grow)
    so the row stays compact instead of stretching or squeezing.

    Scoped via st.container(key="sales_qty_row") to this control only -
    the `.st-key-sales_qty_row` selector cannot affect st.columns()
    layouts used anywhere else in the app (Dashboard, Product
    Management, Alerts, Sales History, etc.).
    """
    st.markdown(
        """
        <style>
        .st-key-sales_qty_row [data-testid="stHorizontalBlock"] {
            flex-wrap: nowrap !important;
            width: max-content !important;
            gap: 0.4rem !important;
        }
        .st-key-sales_qty_row [data-testid="stColumn"] {
            flex: none !important;
            min-width: 0 !important;
        }
        .st-key-sales_qty_row [data-testid="stColumn"]:nth-child(1) { width: 44px !important; }
        .st-key-sales_qty_row [data-testid="stColumn"]:nth-child(2) { width: 40px !important; }
        .st-key-sales_qty_row [data-testid="stColumn"]:nth-child(3) { width: 44px !important; }
        .st-key-sales_qty_row [data-testid="stColumn"]:nth-child(4) { width: 110px !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

@st.fragment
def _render_sale_row(store_id: int, product: dict) -> None:
    """Render one sellable product: its summary line, then a compact
    [-] quantity [+] stepper and Sell button.

    The quantity is not a free-typed number input - it's a small
    integer held in session state, keyed by this product's real
    database product_id (a stable identity, never a list position -
    the same rule established for the Review & Edit table applies
    here, and product_id already satisfies it without needing a
    synthetic id).

    Stock shown/capped here is the FIFO-aware sellable total across
    every lot (batch/expiry) of this medicine name - via
    sales_service.get_sellable_stock - not just this one clicked
    batch row's own quantity, since sell_product() itself now consumes
    earliest-expiry-first across all of this medicine's lots.
    """
    product_id = product["product_id"]
    stock_key = f"sales_stock_{product_id}"
    if stock_key not in st.session_state:
        st.session_state[stock_key] = sales_service.get_sellable_stock(store_id, product["name"])
    stock = st.session_state[stock_key]

    st.markdown(
        f"**{product['name']}**  •  Batch: {product['batch_number']}  •  "
        f"Stock: {stock}  •  Expires: {product['expiry_date']}  •  "
        f"MRP: {product['mrp']}  •  Rate: {product['rate']}"
    )

    qty_key = f"sales_qty_{product_id}"
    quantity = st.session_state.get(qty_key, 1)
    # Defensive clamp: stock may have changed (another sale, or a Product
    # Management edit) since this session_state value was last set.
    quantity = max(1, min(quantity, stock)) if stock > 0 else 1
    st.session_state[qty_key] = quantity

    _render_qty_sell_row_css()

    with st.container(key="sales_qty_row"):
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
                    st.session_state.pop(stock_key, None)
                    bump_cache_epoch()
                    st.success(f"Sold {quantity} × {product['name']}.")
                    st.rerun()
                except ValidationError as error:
                    st.error(str(error))


def _format_sold_at(sold_at: str) -> str:
    """Convert a stored sold_at timestamp to the local timezone and
    format it as "DD MMM YYYY, HH:MM AM/PM" for display.

    sold_at is written by SQLite's own `datetime('now')` default
    (core/database.py), which always produces naive UTC text in
    "YYYY-MM-DD HH:MM:SS" format - confirmed consistent for every row,
    so no schema change or backfill/migration is needed here. This
    function only affects how that value is DISPLAYED, never how it is
    stored: it parses the stored string, explicitly marks it as UTC
    (tzinfo=timezone.utc - it never was naive in meaning, only in
    representation), then converts to the local timezone via
    datetime.astimezone() with no argument, which resolves to whatever
    timezone this server process is running in. This is timezone-aware
    conversion with no hardcoded offset (no "+5:30" or similar) -
    exactly the same conversion Python's own datetime module is
    designed for.

    If a value doesn't match the expected format (e.g. a future schema
    change, or unexpected data), the raw string is returned unchanged
    rather than raising - a single malformed row must never break the
    rest of the Sales History list.
    """
    try:
        utc_dt = datetime.strptime(sold_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        local_dt = utc_dt.astimezone()
        return local_dt.strftime("%d %b %Y, %I:%M %p")
    except (ValueError, TypeError):
        return sold_at


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
                f"Sold: {_format_sold_at(sale['sold_at'])}"
            )
