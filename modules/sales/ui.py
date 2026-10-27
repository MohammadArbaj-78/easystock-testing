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
from modules.sales.bill_ui import render_bill_mode
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


SALES_HISTORY_PAGE_SIZE = 10


@st.cache_data(show_spinner=False, ttl=300)
def _search_suggestions_cached(store_id: int, search_term: str, _epoch: int) -> list:
    return sales_service.search_store_products(store_id, search_term)


@st.cache_data(show_spinner=False, ttl=3600)
def _search_master_cached(search_term: str) -> list:
    """Master medicine list lookup (shared by every store, so not keyed
    by store_id). Only used when the store's own search found nothing."""
    return sales_service.search_master_medicines(search_term)


@st.cache_data(show_spinner=False, ttl=300)
def _get_sales_history_cached(store_id: int, _epoch: int) -> list:
    return sales_service.get_sales_history(store_id)


def _load_more_sales_history() -> None:
    st.session_state["sales_history_visible_limit"] = (
        st.session_state.get("sales_history_visible_limit", SALES_HISTORY_PAGE_SIZE)
        + SALES_HISTORY_PAGE_SIZE
    )

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

    # Bill mode (several medicines, one total, one Sell). With the switch OFF
    # nothing below changes at all.
    if render_bill_mode(store_id):
        return

    search_col, search_btn_col, clear_col = st.columns([5.5, 1.5, 0.8])

    with search_col:
        search_term = st.text_input(
            "Search by medicine name or batch number",
            placeholder="e.g. Paracetamol or B001",
            key="sales_search_term",
        )
    
    with search_btn_col:
        st.button(
            "🔎 Search",
            key="sales_search_button",
            type="primary",
            use_container_width=True,
        )
    
    with clear_col:
        st.button(
            "❌",
            key="sales_clear_search",
            on_click=_clear_search,
            help="Clear search",
            use_container_width=True,
        )
    flash_message = st.session_state.pop("sales_flash_success", None)
    if flash_message:
        st.success(flash_message)

    selected_product = _get_active_selection(store_id, search_term)
    if selected_product is not None:
        _render_sale_row(store_id, selected_product)
        return

    selected_master_name = _get_active_master_selection(search_term)
    if selected_master_name is not None:
        _render_master_save_row(store_id, selected_master_name)
        return

    selected_new_name = _get_active_new_selection(search_term)
    if selected_new_name is not None:
        _render_master_save_row(store_id, selected_new_name, is_new=True)
        return

    if not search_term or not search_term.strip():
        st.info("Start typing a medicine name or batch number.")
        _render_frequently_sold(store_id)
        return

    suggestions = _search_suggestions_cached(store_id, search_term, get_cache_epoch(store_id))

    if not suggestions:
        # Nothing in this store's own stock matches. Only now fall back
        # to the master medicine list - if the store had ANY match above,
        # no master result is ever shown.
        master_results = _search_master_cached(search_term)
        if master_results:
            for master_medicine in master_results:
                _render_master_suggestion_tile(master_medicine)
            return

        # Not in the store and not in the master list either: offer to add
        # exactly what was typed (if it is a usable name).
        is_valid_name, new_name = sales_service.is_valid_new_medicine_name(search_term)
        if is_valid_name:
            _render_add_new_tile(new_name)
        else:
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


def _get_active_master_selection(search_term: str):
    """Return the name of the currently-selected master-list medicine,
    or None. Same stale-selection rule as _get_active_selection: it only
    stays active while the search box still shows exactly that name."""
    name = st.session_state.get("sales_selected_master_name")
    if name is None:
        return None
    if search_term == name:
        return name
    st.session_state.pop("sales_selected_master_name", None)
    return None


def _get_active_new_selection(search_term: str):
    """Same stale-selection rule as _get_active_master_selection, for a
    medicine the owner typed in full that exists nowhere yet."""
    name = st.session_state.get("sales_selected_new_name")
    if name is None:
        return None
    if search_term == name:
        return name
    st.session_state.pop("sales_selected_new_name", None)
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
    st.session_state.pop("sales_selected_master_name", None)
    st.session_state.pop("sales_selected_new_name", None)


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
    st.session_state.pop("sales_selected_master_name", None)
    st.session_state.pop("sales_selected_new_name", None)
    st.session_state[f"sales_qty_{product['product_id']}"] = 1
    st.session_state.pop(f"sales_tabs_{product['product_id']}", None)
    st.session_state.pop(f"sales_tablet_info_{product['product_id']}", None)


def _select_master_medicine(name: str) -> None:
    """on_click callback for a master-list suggestion - same job as
    _select_product (and must be a callback for the same reason): fills
    the search box, marks this medicine selected, resets its quantity to
    1. Marks it by NAME, since it has no product_id yet."""
    st.session_state["sales_search_term"] = name
    st.session_state["sales_selected_master_name"] = name
    st.session_state.pop("sales_selected_product_id", None)
    st.session_state.pop("sales_selected_new_name", None)
    st.session_state[f"sales_master_qty_{name}"] = 1


def _select_new_medicine(name: str) -> None:
    """on_click callback for the "Add as new medicine" tile - same job as
    _select_master_medicine, for a name the owner typed that is in
    neither the store nor the master list."""
    st.session_state["sales_search_term"] = name
    st.session_state["sales_selected_new_name"] = name
    st.session_state.pop("sales_selected_product_id", None)
    st.session_state.pop("sales_selected_master_name", None)
    st.session_state[f"sales_new_qty_{name}"] = 1


def _render_suggestion_tile(product: dict) -> None:
    """Render one compact, single-row suggestion: name, batch, stock
    only - no expiry, MRP, or GST. A dropdown-style list entry, not a
    bordered card - the whole row is one native st.button (Streamlit
    supports basic Markdown in widget labels, including bold text and
    line breaks), so clicking anywhere on the row selects it via the
    on_click callback above. No separate container, no separate
    "Select" sub-button, minimal vertical spacing.
    """
    label = f"**{product['name']}**\nBatch: {_display_value(product['batch_number'])} • Stock: {product['quantity']}"
    st.button(
        label,
        key=f"sales_select_{product['product_id']}",
        use_container_width=True,
        on_click=_select_product,
        args=(product,),
    )


def _render_master_suggestion_tile(medicine: dict) -> None:
    """One master-list suggestion, drawn like a normal suggestion tile
    (a single full-width button). Nothing in the tile says it is not in
    the system - the owner finds that out on click, from the Save row."""
    name = medicine["name"]
    detail = medicine.get("composition") or ""
    label = f"**{name}**\n{detail}" if detail else f"**{name}**"
    st.button(
        label,
        key=f"sales_master_select_{name}",
        use_container_width=True,
        on_click=_select_master_medicine,
        args=(name,),
    )


def _render_add_new_tile(name: str) -> None:
    """The single tile shown when the typed name is found nowhere. It
    shows exactly the text that would be saved, so a typing mistake is
    visible before the owner taps it."""
    st.button(
        f"➕ Add \"{name}\" as a new medicine",
        key="sales_add_new_select",
        use_container_width=True,
        on_click=_select_new_medicine,
        args=(name,),
    )


@st.cache_data(show_spinner=False)
def _get_frequently_sold_cached(store_id: int, _epoch: int) -> list:    
    return sales_service.get_frequently_sold(store_id)

def _render_frequently_sold(store_id: int) -> None:
    """Render the "⭐ Frequently Sold" section shown when the search box
    is empty: top sellers that are still in stock, each clicking exactly
    like a search suggestion.
    """
    frequently_sold = _get_frequently_sold_cached(store_id, get_cache_epoch(store_id))
    
    if not frequently_sold:
        return

    st.markdown("**⭐ Frequently Sold**")
    for product in frequently_sold:
        _render_suggestion_tile(product)


def _render_qty_sell_row_css() -> None:
    """Scoped CSS for the quantity stepper + Sell/Save button, copied in
    spirit from Quick Setup's medicine row (modules/quick_setup/ui.py,
    _inject_medicine_row_css) so the +/- feel is the same on every
    screen, desktop and mobile:
      - Each of the two rows (the - qty + row, and the action row under
        it) is forced to stay ONE line (flex-wrap: nowrap) - Streamlit's
        native st.columns() would otherwise stack them on a phone.
      - The first and last column are fixed-width, so the - and + are
        square buttons (aspect-ratio 1/1); the middle column takes the
        remaining width and holds the centred quantity.
      - The action button (Sell / Save) sits in the LAST column of its
        own row, so it lands directly under the + button.
    Scoped to st.container(key="sales_qty_row") only - the
    .st-key-sales_qty_row selector cannot affect st.columns() layouts
    anywhere else in the app.
    """
    st.markdown(
        """
        <style>
        .st-key-sales_qty_row [data-testid="stHorizontalBlock"] {
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            gap: 0.4rem !important;
            align-items: center !important;
        }
        .st-key-sales_qty_row [data-testid="stColumn"] {
            width: auto !important;
            min-width: 0 !important;
        }
        .st-key-sales_qty_row [data-testid="stColumn"]:first-child,
        .st-key-sales_qty_row [data-testid="stColumn"]:last-child {
            flex: 0 0 64px !important;
        }
        .st-key-sales_qty_row [data-testid="stColumn"]:not(:first-child):not(:last-child) {
            flex: 1 1 auto !important;
        }
        .st-key-sales_qty_row button[kind="secondary"] {
            aspect-ratio: 1 / 1;
            font-size: 1.4rem;
        }
        .st-key-sales_qty_row button[kind="primary"] {
            padding-left: 0.25rem;
            padding-right: 0.25rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _display_value(value) -> str:
    """Show an em dash instead of 'None' or a blank for a value that is
    not known yet (e.g. a medicine saved from the master list has no
    batch/expiry/MRP/rate until its first real invoice is scanned)."""
    if value is None or str(value).strip() == "":
        return "—"
    return str(value)


def _render_stepper_and_action_row(
    *,
    quantity: int,
    qty_key: str,
    max_quantity,
    minus_key: str,
    plus_key: str,
    action_label: str,
    action_key: str,
    action_disabled: bool,
    step: int = 1,
    quantity_label=None,
) -> bool:
    """Render the shared [-] quantity [+] row with the action button
    (Sell or Save) directly under the +. Used by both the normal Sell row
    and the master-list Save row, so the two look and behave identically.

    Must be called from inside an @st.fragment function (the -/+ buttons
    use st.rerun(scope="fragment")).

    Args:
        quantity: Current quantity (already clamped by the caller).
        qty_key: session_state key holding the quantity.
        max_quantity: Upper limit for + (the available stock when
            selling), or None for no limit (saving new stock).

    Returns:
        True if the action button was clicked on this run.
    """
    _render_qty_sell_row_css()

    with st.container(key="sales_qty_row"):
        minus_col, qty_col, plus_col = st.columns([1, 3, 1], vertical_alignment="center")

        with minus_col:
            if st.button("➖", key=minus_key, disabled=(quantity - step < 1), use_container_width=True):
                st.session_state[qty_key] = quantity - step
                st.rerun(scope="fragment")

        with qty_col:
            st.markdown(
                f"<div style='text-align:center; font-size:1.3rem; font-weight:700;'>"
                f"{quantity_label or 'Qty: ' + str(quantity)}</div>",
                unsafe_allow_html=True,
            )

        with plus_col:
            plus_disabled = max_quantity is not None and quantity >= max_quantity
            if st.button("➕", key=plus_key, disabled=plus_disabled, use_container_width=True):
                new_quantity = quantity + step
                if max_quantity is not None:
                    new_quantity = min(new_quantity, max_quantity)
                st.session_state[qty_key] = new_quantity
                st.rerun(scope="fragment")

        _left_spacer, _middle_spacer, action_col = st.columns([1, 3, 1])
        with action_col:
            return st.button(
                action_label,
                key=action_key,
                disabled=action_disabled,
                use_container_width=True,
                type="primary",
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
    stock in arrival order across all of this medicine's lots.
    """
    product_id = product["product_id"]
    tablet_info = _get_tablet_info(store_id, product)
    if tablet_info is not None:
        _render_tablet_sale_row(store_id, product, tablet_info)
        return

    stock_key = f"sales_stock_{product_id}"
    if stock_key not in st.session_state:
        st.session_state[stock_key] = sales_service.get_sellable_stock(store_id, product["name"])
    stock = st.session_state[stock_key]

    st.markdown(
        f"**{product['name']}**  •  Batch: {_display_value(product['batch_number'])}  •  "
        f"Stock: {stock}  •  Expires: {_display_value(product['expiry_date'])}  •  "
        f"MRP: {_display_value(product['mrp'])}  •  Rate: {_display_value(product['rate'])}"
    )

    qty_key = f"sales_qty_{product_id}"
    quantity = st.session_state.get(qty_key, 1)
    # Defensive clamp: stock may have changed (another sale, or a Product
    # Management edit) since this session_state value was last set.
    quantity = max(1, min(quantity, stock)) if stock > 0 else 1
    st.session_state[qty_key] = quantity

    sell_clicked = _render_stepper_and_action_row(
        quantity=quantity,
        qty_key=qty_key,
        max_quantity=stock,
        minus_key=f"sales_minus_{product_id}",
        plus_key=f"sales_plus_{product_id}",
        action_label="Sell",
        action_key=f"sales_sell_{product_id}",
        action_disabled=(stock == 0),
    )

    if sell_clicked:
        try:
            sales_service.sell_product(store_id, product_id, quantity)
            st.session_state[qty_key] = 1
            st.session_state.pop(stock_key, None)
            bump_cache_epoch(store_id)
            st.success(f"Sold {quantity} × {product['name']}.")
            st.rerun()
        except ValidationError as error:
            st.error(str(error))


def _format_tablets(tablets: int, pack: int) -> str:
    """Tablets as strips + loose tablets: 28 of a 15-pack -> "1 strip + 13
    tablets"; 30 -> "2 strips"; 10 -> "10 tablets". Never a decimal."""
    strips, loose = divmod(int(tablets), int(pack))
    parts = []
    if strips:
        parts.append(f"{strips} strip" + ("" if strips == 1 else "s"))
    if loose or not parts:
        parts.append(f"{loose} tablet" + ("" if loose == 1 else "s"))
    return " + ".join(parts)


def _format_sold_quantity(sale: dict) -> str:
    """The quantity of one sales-history row. A whole number of strips as
    before; part of a strip as tablets (the row stores its pack size)."""
    quantity = sale["sold_quantity"]
    pack = sale.get("pack_size")
    try:
        quantity = float(quantity)
    except (TypeError, ValueError):
        return str(quantity)
    if abs(quantity - round(quantity)) < 1e-9:
        return str(int(round(quantity)))
    if pack:
        return _format_tablets(int(round(quantity * float(pack))), int(pack))
    return f"{quantity:.2f}"


def _get_tablet_info(store_id: int, product: dict):
    """{"pack", "tablets"} if this medicine can be sold by the tablet, else
    None. Kept in session_state per medicine and re-read whenever the
    medicine is picked again or sold."""
    key = f"sales_tablet_info_{product['product_id']}"
    if key not in st.session_state:
        st.session_state[key] = sales_service.get_tablet_stock(store_id, product["name"])
    return st.session_state[key]


def _remember_unit_choice(mode_key: str) -> None:
    st.session_state["sales_unit_choice"] = st.session_state[mode_key]


def _render_tablet_sale_row(store_id: int, product: dict, info: dict) -> None:
    """The Sell row for a medicine whose pack size is known: the same
    [-] quantity [+] and Sell button, plus a Strip | Tablet choice above it
    that sets the STEP of - and +: a whole strip, or one tablet. Strip is the
    default; the last choice is remembered. The quantity is shown as
    "1 strip + 3 tablets", never as a decimal, and is kept as a whole number
    of tablets underneath."""
    product_id = product["product_id"]
    pack, stock = info["pack"], info["tablets"]

    st.markdown(
        f"**{product['name']}**  •  Batch: {_display_value(product['batch_number'])}  •  "
        f"Stock: {_format_tablets(stock, pack)}  •  Expires: {_display_value(product['expiry_date'])}  •  "
        f"MRP: {_display_value(product['mrp'])}  •  Rate: {_display_value(product['rate'])}"
    )

    mode_key = f"sales_unit_{product_id}"
    if mode_key not in st.session_state:
        st.session_state[mode_key] = st.session_state.get("sales_unit_choice", "Strip")
    st.radio(
        "Unit", ["Strip", "Tablet"], key=mode_key, horizontal=True,
        label_visibility="collapsed", on_change=_remember_unit_choice, args=(mode_key,),
    )
    step = 1 if st.session_state[mode_key] == "Tablet" else pack

    tabs_key = f"sales_tabs_{product_id}"
    if tabs_key not in st.session_state:
        st.session_state[tabs_key] = min(step, stock)
    # Defensive clamp: stock may have changed since this value was set.
    tablets = max(1, min(st.session_state[tabs_key], stock)) if stock > 0 else 1
    st.session_state[tabs_key] = tablets

    sell_clicked = _render_stepper_and_action_row(
        quantity=tablets,
        qty_key=tabs_key,
        max_quantity=stock,
        minus_key=f"sales_minus_{product_id}",
        plus_key=f"sales_plus_{product_id}",
        action_label="Sell",
        action_key=f"sales_sell_{product_id}",
        action_disabled=(stock == 0),
        step=step,
        quantity_label=f"Qty: {_format_tablets(tablets, pack)}",
    )

    if sell_clicked:
        try:
            sales_service.sell_tablets(store_id, product_id, tablets)
            st.session_state.pop(tabs_key, None)
            st.session_state.pop(f"sales_tablet_info_{product_id}", None)
            st.session_state.pop(f"sales_stock_{product_id}", None)
            bump_cache_epoch(store_id)
            st.success(f"Sold {_format_tablets(tablets, pack)} × {product['name']}.")
            st.rerun()
        except ValidationError as error:
            st.error(str(error))


@st.fragment
def _render_master_save_row(store_id: int, name: str, is_new: bool = False) -> None:
    """The same row as _render_sale_row, for a medicine picked from the
    master list that is not in this store's system yet: identical
    [-] quantity [+] layout, but the button says Save (it stores the
    medicine with that quantity) instead of Sell, and a red warning
    underneath tells the owner it is not in the system.

    There is no stock to cap against, so + has no upper limit.
    """
    st.markdown(f"**{name}**")

    key_stem = "sales_new" if is_new else "sales_master"
    selection_key = "sales_selected_new_name" if is_new else "sales_selected_master_name"
    qty_key = f"{key_stem}_qty_{name}"
    quantity = max(1, st.session_state.get(qty_key, 1))
    st.session_state[qty_key] = quantity

    save_clicked = _render_stepper_and_action_row(
        quantity=quantity,
        qty_key=qty_key,
        max_quantity=None,
        minus_key=f"{key_stem}_minus_{name}",
        plus_key=f"{key_stem}_plus_{name}",
        action_label="Save",
        action_key=f"{key_stem}_save_{name}",
        action_disabled=False,
    )

    if is_new:
        st.error(
            "⚠️ This medicine was not found in your system or in the medicine list. "
            "Please check the spelling, set the quantity and save it."
        )
    else:
        st.error(
            "⚠️ This medicine is not in your system. "
            "Please set the correct quantity and save it."
        )

    if save_clicked:
        try:
            if is_new:
                sales_service.save_new_medicine(store_id, name, quantity)
            else:
                sales_service.save_master_medicine(store_id, name, quantity)
        except ValidationError as error:
            st.error(str(error))
        except Exception as error:
            st.error(f"Could not save this medicine right now: {error}")
        else:
            st.session_state.pop(qty_key, None)
            st.session_state.pop(selection_key, None)
            st.session_state["sales_flash_success"] = f"Saved {quantity} × {name} to your system."
            bump_cache_epoch(store_id)
            st.rerun()


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


@st.fragment
def _render_sales_history_section() -> None:
    """Render the read-only Sales History: latest 100, newest first,
    as native bordered-container cards. No edit, no delete, no
    filters, no pagination.
    """
    store_id = get_current_store_id()

    st.markdown("**🧾 Sales History**")

    sales = _get_sales_history_cached(store_id, get_cache_epoch(store_id))

    if not sales:
        st.info("No sales recorded yet.")
        return

    limit = st.session_state.get("sales_history_visible_limit", SALES_HISTORY_PAGE_SIZE)

    for sale in sales[:limit]:
        with st.container(border=True):
            st.markdown(f"**{sale['medicine_name']}**")
            st.caption(
                f"Batch: {sale['batch_number']}  •  "
                f"Sold Qty: {_format_sold_quantity(sale)}  •  "
                f"Sold: {_format_sold_at(sale['sold_at'])}"
            )
    
    if len(sales) > limit:
        st.caption(f"Showing {limit} of {len(sales)}")
        st.button(
            f"⬇️ Load {min(SALES_HISTORY_PAGE_SIZE, len(sales) - limit)} more",
            key="sales_history_load_more",
            use_container_width=True,
            on_click=_load_more_sales_history,
        )