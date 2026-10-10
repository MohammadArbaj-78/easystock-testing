"""
Quick Setup screen UI.

Lets a store owner build up their starting stock FAST - search India's
medicine master list, tap +/- to set quantities like a simple counter
game, and Save All at once. Batch/expiry/MRP/rate get filled in
properly the first time a real invoice for that medicine is scanned.
"""

import streamlit as st

from modules.quick_setup import service as quick_setup_service
from core.session import get_current_store_id
from core.cache_utils import bump_cache_epoch

SEARCH_RESULT_LIMIT = 20
_CART_KEY = "quick_setup_cart"


BROWSE_PAGE_SIZE = 20


def render_quick_setup_page() -> None:
    """Render the Quick Setup screen."""
    _inject_medicine_row_css()
    st.subheader("⚡ Quick Setup")
    st.caption(
        "Naye store ke liye: medicine search karo, Excel/CSV upload "
        "karo, ya niche list browse karo - +/- se quantity set karo, "
        "aur ek saath Save All karo."
    )

    store_id = get_current_store_id()
    cart = st.session_state.setdefault(_CART_KEY, {})

    # Save bar is OUTSIDE the tabs - it works on the shared cart, so
    # selections made in EITHER tab (database search/browse, or an
    # uploaded file) get saved together with one click.
    _render_sticky_save_bar(store_id, cart)

    search_tab, upload_tab = st.tabs(["🔍 Database Search", "📤 Upload Excel/CSV"])
    with search_tab:
        _render_database_search_tab(store_id, cart)
    with upload_tab:
        _render_upload_tab(store_id, cart)


def _render_database_search_tab(store_id: int, cart: dict) -> None:
    """The original Quick Setup tab: search the medicine master list,
    or browse it page-by-page with A-Z jump navigation."""
    search_col, button_col = st.columns([5, 1.3])
    with search_col:
        search_term = st.text_input(
            "Medicine search karo",
            key="quick_setup_search_term",
            placeholder="e.g. Dolo, Paracetamol, Augmentin",
            label_visibility="collapsed",
        )
    with button_col:
        st.button("🔎 Search", key="quick_setup_search_button", use_container_width=True)

    if search_term and search_term.strip():
        results = quick_setup_service.search_medicines(search_term, SEARCH_RESULT_LIMIT)
        if not results:
            st.warning("Koi medicine nahi mili. Spelling check karo ya chhota naam try karo.")
            return
        if len(results) == SEARCH_RESULT_LIMIT:
            st.caption(f"Top {SEARCH_RESULT_LIMIT} results dikha rahe hain. Zyada specific likho.")
        for index, medicine in enumerate(results):
            _render_medicine_block(store_id, medicine, cart, index)
        return

    if "quick_setup_browse_page" not in st.session_state:
        st.session_state["quick_setup_browse_page"] = quick_setup_service.get_last_page(store_id)

    total_medicines = quick_setup_service.count_medicines()
    total_pages = max(1, -(-total_medicines // BROWSE_PAGE_SIZE))
    current_page = min(max(1, st.session_state["quick_setup_browse_page"]), total_pages)

    jump_reset_key = "_clear_quick_setup_jump_letter"
    if st.session_state.pop(jump_reset_key, False):
        st.session_state["quick_setup_jump_letter"] = None

    letter_col, _spacer = st.columns([1, 3])
    with letter_col:
        selected_letter = st.selectbox(
            "Jump to letter", list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
            key="quick_setup_jump_letter", index=None,
            placeholder="A-Z",
        )
    if selected_letter:
        target_page = quick_setup_service.find_page_for_letter(selected_letter, BROWSE_PAGE_SIZE)
        st.session_state["quick_setup_browse_page"] = target_page
        quick_setup_service.save_last_page(store_id, target_page)
        current_page = target_page
        st.session_state[jump_reset_key] = True

    with st.container(key="qs_pager"):
        prev_col, label_col, next_col = st.columns([1, 2, 1])
        with prev_col:
            st.button("⬅️ Prev", key="quick_setup_prev_page", use_container_width=True,
                       disabled=current_page <= 1, on_click=_change_page, args=(store_id, -1, total_pages))
        with label_col:
            st.markdown(f"<div style='text-align:center;'>Page {current_page} of {total_pages}</div>", unsafe_allow_html=True)
        with next_col:
            st.button("Next ➡️", key="quick_setup_next_page", use_container_width=True,
                       disabled=current_page >= total_pages, on_click=_change_page, args=(store_id, 1, total_pages))

    visible = quick_setup_service.browse_medicines_page(current_page, BROWSE_PAGE_SIZE)
    for index, medicine in enumerate(visible):
        _render_medicine_block(store_id, medicine, cart, index)

_NAME_COLUMN_CANDIDATES = ["name", "medicine", "medicine name", "product", "product name", "item", "item name"]
_QUANTITY_COLUMN_CANDIDATES = ["quantity", "qty", "stock", "stock qty", "available qty", "current stock", "balance qty"]


def _render_upload_tab(store_id: int, cart: dict) -> None:
    """Upload a distributor/seller's own Excel/CSV stock file - parsed
    rows are previewed below using the SAME medicine-block UI (+/-,
    Load more) as the database-search tab, and feed into the SAME
    shared cart, so one Save All (above the tabs) saves everything."""
    st.caption(
        "Distributor/seller ki Excel ya CSV file upload karo. File mein "
        "medicine naam aur quantity ka column hona chahiye (jaise "
        "'Name'/'Medicine' aur 'Quantity'/'Qty')."
    )
    uploaded_file = st.file_uploader(
        "Excel ya CSV file chuno", type=["xlsx", "xls", "csv"],
        key="quick_setup_uploaded_file",
    )
    if uploaded_file is None:
        st.session_state.pop("quick_setup_uploaded_rows", None)
        st.session_state.pop("quick_setup_uploaded_file_name", None)
        return

    if st.session_state.get("quick_setup_uploaded_file_name") != uploaded_file.name:
        try:
            rows = _parse_uploaded_stock_file(uploaded_file)
        except ValueError as error:
            st.error(str(error))
            return
        st.session_state["quick_setup_uploaded_rows"] = rows
        st.session_state["quick_setup_uploaded_file_name"] = uploaded_file.name
        st.session_state["quick_setup_upload_limit"] = BROWSE_PAGE_SIZE
        for row in rows:
            cart[row["name"]] = row["quantity"]

    rows = st.session_state.get("quick_setup_uploaded_rows", [])
    if not rows:
        st.warning("Is file mein koi usable row nahi mili.")
        return

    st.success(f"✅ {len(rows)} medicine(s) file mein mili. Niche check/adjust karo, phir upar Save All dabao.")

    limit = st.session_state.get("quick_setup_upload_limit", BROWSE_PAGE_SIZE)
    visible = rows[:limit]
    for index, row in enumerate(visible):
        fake_medicine = {"name": row["name"], "manufacturer_name": "", "composition": ""}
        _render_medicine_block(store_id, fake_medicine, cart, f"u{index}")

    if len(rows) > limit:
        st.caption(f"Showing {limit} of {len(rows)}")
        st.button(
            f"⬇️ Load {min(BROWSE_PAGE_SIZE, len(rows) - limit)} more",
            key="quick_setup_upload_load_more", use_container_width=True,
            on_click=_load_more_upload,
        )


def _load_more_upload() -> None:
    st.session_state["quick_setup_upload_limit"] = (
        st.session_state.get("quick_setup_upload_limit", BROWSE_PAGE_SIZE) + BROWSE_PAGE_SIZE
    )


import re

_NAME_HEADER_KEYWORDS = ["name", "medicine", "product", "item", "drug"]
_QUANTITY_HEADER_KEYWORDS = ["qty", "quantity", "stock", "balance", "available", "count"]


def _normalize_header(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def _find_column(dataframe, keywords):
    for col in dataframe.columns:
        normalized = _normalize_header(col)
        if any(keyword in normalized for keyword in keywords):
            return col
    return None


def _parse_uploaded_stock_file(uploaded_file) -> list:
    """Parse an uploaded Excel/CSV into [{"name": str, "quantity": float}].

    Matches a name-like and quantity-like column by FLEXIBLE keyword
    matching on the header (case/punctuation/spacing-insensitive), so
    "Medicine Name", "Item_Name", "Available Qty" etc. all work -
    exact column order/extra columns don't matter.

    Raises:
        ValueError: If the file can't be read, or no matching columns
            were found (lists the file's actual headers, so the real
            cause is visible instead of a generic "not found").
    """
    import pandas as pd

    try:
        if uploaded_file.name.lower().endswith(".csv"):
            dataframe = pd.read_csv(uploaded_file)
        else:
            dataframe = pd.read_excel(uploaded_file)
    except Exception as error:
        raise ValueError(f"File padhi nahi ja saki: {error}") from error

    name_column = _find_column(dataframe, _NAME_HEADER_KEYWORDS)
    quantity_column = _find_column(dataframe, _QUANTITY_HEADER_KEYWORDS)

    if name_column is None or quantity_column is None:
        found = ", ".join(str(c) for c in dataframe.columns)
        raise ValueError(
            "File mein medicine naam aur quantity wala column nahi mila. "
            f"File mein ye columns hain: {found}. "
            "Column header mein kahin 'name'/'medicine'/'item' aur "
            "'qty'/'quantity'/'stock' jaisa shabd hona chahiye."
        )

    rows = []
    for _, record in dataframe.iterrows():
        name = str(record[name_column] or "").strip()
        if not name or name.lower() == "nan":
            continue
        try:
            quantity = float(record[quantity_column])
        except (ValueError, TypeError):
            continue
        if quantity <= 0:
            continue
        rows.append({"name": name, "quantity": quantity})
    return rows

def _change_page(store_id: int, delta: int, total_pages: int) -> None:
    new_page = min(max(1, st.session_state["quick_setup_browse_page"] + delta), total_pages)
    st.session_state["quick_setup_browse_page"] = new_page
    quick_setup_service.save_last_page(store_id, new_page)
    
def _inject_medicine_row_css() -> None:
    """Forces each medicine row's -/name/+ (and the Prev/Page/Next bar)
    into ONE line, never stacked. Scoped ONLY to containers created
    with a key starting with "qs_row_" or "qs_pager" (Streamlit adds a
    stable st-key-<key> class to such containers) - this NEVER
    touches the search bar's or Save bar's own columns, since those
    containers don't have this key prefix."""
    st.markdown(
        """
        <style>
        div[class*="st-key-qs_row_"] div[data-testid="stHorizontalBlock"],
        div[class*="st-key-qs_pager"] div[data-testid="stHorizontalBlock"] {
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            gap: 0.4rem !important;
            align-items: center !important;
        }
        div[class*="st-key-qs_row_"] div[data-testid="stColumn"],
        div[class*="st-key-qs_pager"] div[data-testid="stColumn"] {
            width: auto !important;
            min-width: 0 !important;
        }
        div[class*="st-key-qs_row_"] div[data-testid="stColumn"]:first-child,
        div[class*="st-key-qs_row_"] div[data-testid="stColumn"]:last-child {
            flex: 0 0 56px !important;
        }
        div[class*="st-key-qs_row_"] div[data-testid="stColumn"]:not(:first-child):not(:last-child) {
            flex: 1 1 auto !important;
        }
        div[class*="st-key-qs_pager"] div[data-testid="stColumn"] {
            flex: 1 1 0 !important;
        }
        div[class*="st-key-qs_row_"] button[kind="secondary"] {
            aspect-ratio: 1 / 1;
            font-size: 1.4rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

def _render_sticky_save_bar(store_id: int, cart: dict) -> None:
    """A save bar that stays visible while scrolling (CSS position:
    sticky). NOTE: sticky positioning inside Streamlit's iframe can
    behave slightly differently across mobile browsers - verify on a
    real phone after deploying; if it doesn't stick, the bar still
    works as a normal (non-sticky) bar at the top.
    """
    selected = {name: qty for name, qty in cart.items() if qty and qty > 0}
    count = len(selected)
    total_qty = sum(selected.values())

    st.markdown(
        """
        <style>
        div[data-testid="stVerticalBlock"] > div:has(> div.quick-setup-save-anchor) {
            position: sticky;
            top: 0;
            z-index: 999;
            background: var(--background-color, #fff);
            padding: 0.5rem 0;
        }
        </style>
        <div class="quick-setup-save-anchor"></div>
        """,
        unsafe_allow_html=True,
    )

    save_col, count_col = st.columns([1, 2])
    with save_col:
        save_clicked = st.button(
            "💾 Save All",
            key="quick_setup_save_button",
            type="primary",
            use_container_width=True,
            disabled=count == 0,
        )
    with count_col:
        if count:
            st.caption(f"✅ {count} medicine(s) selected • Total qty: {total_qty:g}")
        else:
            st.caption("Koi medicine select nahi hui abhi.")

    if save_clicked and count:
        saved = quick_setup_service.save_quantities(store_id, selected)
        bump_cache_epoch(store_id)
        st.session_state[_CART_KEY] = {}
        st.success(f"✅ {saved} medicine(s) ki quantity save ho gayi.")
        st.rerun()

    st.divider()


def _render_medicine_block(store_id: int, medicine: dict, cart: dict, index) -> None:
    """One big, tap-friendly block per medicine: name centered, square
    -/+ on either side, quantity shown inline next to the name."""
    name = medicine["name"]

    if name not in cart:
        cart[name] = quick_setup_service.get_saved_quantity(store_id, name)

    quantity = cart[name]
    row_key = f"qs_row_{index}"

    with st.container(border=True, key=row_key):
        minus_col, name_col, plus_col = st.columns([1, 3, 1], vertical_alignment="center")

        with minus_col:
            st.button(
                "➖", key=f"{row_key}_minus",
                use_container_width=True,
                on_click=_adjust_quantity, args=(cart, name, -1),
            )
        with name_col:
            subtitle = medicine.get("manufacturer_name") or medicine.get("composition") or ""
            st.markdown(
                f"<div style='text-align:center;'>"
                f"<div style='font-size:1.05rem; font-weight:600;'>{name}</div>"
                f"<div style='font-size:0.75rem; color:#888;'>{subtitle}</div>"
                f"<div style='font-size:1.3rem; font-weight:700; margin-top:2px;'>"
                f"Qty: {quantity:g}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        with plus_col:
            st.button(
                "➕", key=f"{row_key}_plus",
                use_container_width=True,
                on_click=_adjust_quantity, args=(cart, name, 1),
            )


def _adjust_quantity(cart: dict, name: str, delta: int) -> None:
    cart[name] = max(0, cart.get(name, 0) + delta)

def _set_quantity_from_input(cart: dict, name: str, qty_input_key: str) -> None:
    cart[name] = max(0, int(st.session_state.get(qty_input_key, 0)))