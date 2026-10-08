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


def render_quick_setup_page() -> None:
    """Render the Quick Setup screen."""
    st.subheader("⚡ Quick Setup")
    st.caption(
        "Naye store ke liye: medicine search karo, +/- se quantity set "
        "karo, aur ek saath Save All karo. Baad mein jab asli invoice "
        "scan hoga, batch/expiry/MRP/rate apne aap bhar jaayenge."
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

    if not search_term or not search_term.strip():
        st.info("Upar search box mein medicine ka naam likho.")
        return

    results = quick_setup_service.search_medicines(search_term, SEARCH_RESULT_LIMIT)
    if not results:
        st.warning("Koi medicine nahi mili. Spelling check karo ya chhota naam try karo.")
        return

    if len(results) == SEARCH_RESULT_LIMIT:
        st.caption(f"Top {SEARCH_RESULT_LIMIT} results dikha rahe hain. Zyada specific likho aur dhoondh paoge.")

    for medicine in results:
        _render_medicine_block(store_id, medicine, cart)


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


def _render_medicine_block(store_id: int, medicine: dict, cart: dict) -> None:
    """One big, tap-friendly block per medicine: name centered, -/+ on
    either side, quantity shown inline next to the name."""
    name = medicine["name"]

    if name not in cart:
        cart[name] = quick_setup_service.get_saved_quantity(store_id, name)

    quantity = cart[name]
    safe_key = "".join(ch if ch.isalnum() else "_" for ch in name)
    
    # --- यहाँ नया कोड जोड़ें ---
    # दवा के निर्माता या कंपोजिशन का नाम लेकर उसे सुरक्षित अक्षरों में बदलें ताकि चाबी हमेशा यूनिक रहे
    extra_info = medicine.get("manufacturer_name") or medicine.get("composition") or "default"
    safe_extra = "".join(ch if ch.isalnum() else "_" for ch in extra_info)
    unique_key = f"{safe_key}_{safe_extra}"
    # ---------------------------

    with st.container(border=True):
        minus_col, name_col, plus_col = st.columns([1, 4, 1])

        with minus_col:
            st.button(
                "➖", key=f"qs_minus_{unique_key}", # यहाँ safe_key की जगह unique_key लिखा
                use_container_width=True,
                on_click=_adjust_quantity, args=(cart, name, -1),
            )
        with name_col:
            subtitle = medicine.get("manufacturer_name") or medicine.get("composition") or ""
            st.markdown(
                f"<div style='text-align:center;'>"
                f"<div style='font-size:1.1rem; font-weight:600;'>{name}</div>"
                f"<div style='font-size:0.8rem; color:#888;'>{subtitle}</div>"
                f"<div style='font-size:1.4rem; font-weight:700; margin-top:4px;'>"
                f"Qty: {quantity:g}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        with plus_col:
            st.button(
                "➕", key=f"qs_plus_{unique_key}", # यहाँ भी safe_key की जगह unique_key लिखा
                use_container_width=True,
                on_click=_adjust_quantity, args=(cart, name, 1),
            )

        with name_col:
            subtitle = medicine.get("manufacturer_name") or medicine.get("composition") or ""
            st.markdown(
                f"<div style='text-align:center;'>"
                f"<div style='font-size:1.1rem; font-weight:600;'>{name}</div>"
                f"<div style='font-size:0.8rem; color:#888;'>{subtitle}</div>"
                f"<div style='font-size:1.4rem; font-weight:700; margin-top:4px;'>"
                f"Qty: {quantity:g}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        with plus_col:
            st.button(
                "➕", key=f"qs_plus_{safe_key}",
                use_container_width=True,
                on_click=_adjust_quantity, args=(cart, name, 1),
            )


def _adjust_quantity(cart: dict, name: str, delta: int) -> None:
    cart[name] = max(0, cart.get(name, 0) + delta)