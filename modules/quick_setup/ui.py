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
    st.subheader("⚡ Quick Setup")
    st.caption(
        "Naye store ke liye: medicine search karo (ya niche list browse "
        "karo), +/- se quantity set karo, aur ek saath Save All karo."
    )

    store_id = get_current_store_id()
    cart = st.session_state.setdefault(_CART_KEY, {})

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

    _render_sticky_save_bar(store_id, cart)

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

    # Search blank -> browse the master list directly (Products-style Load more).
    limit = st.session_state.get("quick_setup_browse_limit", BROWSE_PAGE_SIZE)
    browsed = quick_setup_service.browse_medicines(limit + 1)
    has_more = len(browsed) > limit
    visible = browsed[:limit]

    if not visible:
        st.info("Abhi master list mein koi medicine nahi mili.")
        return

    for index, medicine in enumerate(visible):
        _render_medicine_block(store_id, medicine, cart, index)

    if has_more:
        st.button(
            f"⬇️ Load {BROWSE_PAGE_SIZE} more",
            key="quick_setup_browse_load_more",
            use_container_width=True,
            on_click=_load_more_browse,
        )


def _load_more_browse() -> None:
    st.session_state["quick_setup_browse_limit"] = (
        st.session_state.get("quick_setup_browse_limit", BROWSE_PAGE_SIZE) + BROWSE_PAGE_SIZE
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


def _render_medicine_block(store_id: int, medicine: dict, cart: dict, index: int) -> None:
    """One big, tap-friendly block per medicine: name centered, with
    square -/+ buttons on either side and the current quantity shown
    inline next to the name - like adjusting a counter in a simple
    game."""
    name = medicine["name"]

    if name not in cart:
        cart[name] = quick_setup_service.get_saved_quantity(store_id, name)

    quantity = cart[name]
    # Keyed by INDEX, not name - the master dataset has duplicate
    # names (same medicine from different manufacturers), so a
    # name-based key crashed with "DuplicateElementKey". The cart
    # itself still stays keyed by name on purpose - every duplicate
    # row for the same name shares (and sets) the same quantity.
    row_key = f"qs_row_{index}"

    st.markdown(
        """
        <style>
        div[data-testid="stHorizontalBlock"] button[kind="secondary"] {
            aspect-ratio: 1 / 1;
            font-size: 1.5rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container(border=True):
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