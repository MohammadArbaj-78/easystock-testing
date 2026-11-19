"""
Udhar Khata screen: customers who take medicines on credit.

List of customers (who owes how much) -> tap a customer -> "Udhar diya" /
"Paise mile" entries, history, and a WhatsApp reminder. No business logic
here - modules.udhar.service does that.
"""

import html
from datetime import date

import streamlit as st

from core.session import get_current_store_id, get_current_store_name
from modules.udhar import service

try:
    from st_keyup import st_keyup
except ImportError:          # package not installed: a normal text box is used instead
    st_keyup = None

_STATE = "udhar_state"
_SELECTED = "udhar_selected"
_MODE = "udhar_mode"              # "gave" / "got" while the entry form is open
_CONFIRM = "udhar_confirm_delete"
_FLASH = "udhar_flash"
_KEYUP_DEBOUNCE_MS = 150
_RED = "#D32F2F"
_GREEN = "#2E7D32"

_TABLE_HELP = (
    "Udhar Khata abhi shuru nahi ho saka. Supabase me `database/udhar_khata.sql` "
    "ek baar chalani hai. Detail: "
)


def render_udhar_page() -> None:
    st.subheader("📒 Udhar Khata")
    try:
        store_id = get_current_store_id()
        selected = st.session_state.get(_SELECTED)
        if selected is not None and _find_customer(store_id, selected) is not None:
            _render_customer(store_id, selected)
        else:
            st.session_state.pop(_SELECTED, None)
            _render_list(store_id)
    except Exception as error:
        st.error(_TABLE_HELP + str(error))


# ---------------------------------------------------------------- state

def _state(store_id: int) -> dict:
    """Customers (with balances) and opened histories: read once, kept in the
    session, read again only after this screen changes something."""
    state = st.session_state.get(_STATE)
    if state is None or state["store_id"] != store_id:
        state = {"store_id": store_id, "customers": service.get_customers(store_id), "history": {}}
        st.session_state[_STATE] = state
    return state


def _refresh(store_id: int) -> None:
    st.session_state[_STATE] = {"store_id": store_id, "customers": service.get_customers(store_id), "history": {}}


def _find_customer(store_id: int, customer_id: int):
    return next((row for row in _state(store_id)["customers"] if row["customer_id"] == customer_id), None)


def _history(store_id: int, customer: dict) -> list:
    state = _state(store_id)
    cache = state["history"]
    if customer["customer_id"] not in cache:
        cache[customer["customer_id"]] = service.get_history(store_id, customer["customer_id"], customer["balance"])
    return cache[customer["customer_id"]]


def _balance_text(balance: float) -> str:
    if balance > 0:
        return f"{service.money(balance)} baaki"
    if balance < 0:
        return f"{service.money(balance)} advance"
    return "Hisaab barabar ✅"


def _show_flash() -> None:
    flash = st.session_state.pop(_FLASH, None)
    if flash:
        getattr(st, flash[0])(flash[1])


# ------------------------------------------------------------ list view

def _open_customer(customer_id: int) -> None:
    st.session_state[_SELECTED] = customer_id
    st.session_state.pop(_MODE, None)
    st.session_state.pop(_CONFIRM, None)


def _search_box() -> str:
    hint = "Naam ya mobile se dhoondho"
    if st_keyup is not None:
        try:
            text = st_keyup(
                "Search customer", placeholder=hint, debounce=_KEYUP_DEBOUNCE_MS,
                key="udhar_search", label_visibility="collapsed",
            )
        except TypeError:
            text = st_keyup("Search customer", debounce=_KEYUP_DEBOUNCE_MS, key="udhar_search")
        return text or ""
    return st.text_input("Search customer", placeholder=hint, key="udhar_search", label_visibility="collapsed") or ""


def _card(title: str, value: str, color: str) -> None:
    st.markdown(
        "<div style='text-align:center; padding:0.4rem 0;'>"
        f"<div style='font-size:0.8rem; color:#888;'>{html.escape(title)}</div>"
        f"<div style='font-size:1.5rem; font-weight:800; color:{color};'>{html.escape(value)}</div>"
        "</div>",
        unsafe_allow_html=True,
    )


@st.fragment
def _render_list(store_id: int) -> None:
    """A fragment: typing in the search box redraws only this list."""
    customers = _state(store_id)["customers"]
    _show_flash()

    totals = service.summary(customers)
    left, right = st.columns(2)
    with left:
        _card("Kul lena hai", service.money(totals["total"]), _RED if totals["total"] > 0 else _GREEN)
    with right:
        _card("Kitno ka baaki", str(totals["count"]), "inherit")

    _render_add_customer(store_id)

    if not customers:
        st.info("Abhi koi customer nahi hai. Upar ➕ se pehla customer jodo.")
        return

    term = _search_box().strip().lower()
    digits = "".join(ch for ch in term if ch.isdigit())
    shown = [
        row for row in customers
        if not term or term in row["name"].lower() or (digits and digits in row["mobile"])
    ]
    if not shown:
        st.info("Koi customer nahi mila.")
        return
    for row in shown:
        label = f"**{row['name']}**  •  {_balance_text(row['balance'])}\n📱 {row['mobile']}"
        if st.button(label, key=f"udhar_open_{row['customer_id']}", use_container_width=True):
            _open_customer(row["customer_id"])
            st.rerun()                       # the whole page: the customer screen replaces the list


def _render_add_customer(store_id: int) -> None:
    with st.expander("➕ Naya customer"):
        with st.form("udhar_new_customer", clear_on_submit=True):
            name = st.text_input("Naam", placeholder="Customer ka naam")
            mobile = st.text_input("Mobile number", placeholder="10 ank ka number")
            submitted = st.form_submit_button("Save", type="primary", use_container_width=True)
        if not submitted:
            return
        result = service.add_customer(store_id, name, mobile)
        status = result["status"]
        if status == "added":
            _refresh(store_id)
            _open_customer(result["customer_id"])
            st.rerun()
        elif status == "exists":
            st.warning(f"Ye number pehle se hai: {result.get('name', '')}.")
        elif status == "bad_name":
            st.warning("Naam 2 se 60 akshar ka likho.")
        else:
            st.warning("Sahi 10 ank ka mobile number likho.")


# -------------------------------------------------------- customer view

def _back() -> None:
    st.session_state.pop(_SELECTED, None)
    st.session_state.pop(_MODE, None)
    st.session_state.pop(_CONFIRM, None)


def _set_mode(mode: str) -> None:
    st.session_state[_MODE] = None if st.session_state.get(_MODE) == mode else mode


def _ask_delete(entry_id: int) -> None:
    st.session_state[_CONFIRM] = entry_id


def _cancel_delete() -> None:
    st.session_state.pop(_CONFIRM, None)


def _do_delete(store_id: int, entry_id: int) -> None:
    service.delete_entry(store_id, entry_id)
    st.session_state.pop(_CONFIRM, None)
    _refresh(store_id)
    st.session_state[_FLASH] = ("success", "Entry hata di gayi.")


@st.fragment
def _render_customer(store_id: int, customer_id: int) -> None:
    """A fragment: entries, delete and the forms redraw only this screen."""
    customer = _find_customer(store_id, customer_id)
    if customer is None:
        return
    if st.button("← Sab customers", key="udhar_back", on_click=_back):
        st.rerun()                           # back to the list: the whole page

    _show_flash()
    balance = customer["balance"]
    color = _RED if balance > 0 else _GREEN
    st.markdown(
        "<div style='text-align:center; margin:0.3rem 0;'>"
        f"<div style='font-size:1.3rem; font-weight:700;'>{html.escape(customer['name'])}</div>"
        f"<div style='font-size:0.85rem; color:#888;'>📱 {html.escape(customer['mobile'])}</div>"
        f"<div style='font-size:1.8rem; font-weight:800; color:{color};'>{html.escape(_balance_text(balance))}</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    gave_col, got_col = st.columns(2)
    mode = st.session_state.get(_MODE)
    with gave_col:
        st.button(
            "🔴 Udhar diya", key="udhar_mode_gave", use_container_width=True,
            type="primary" if mode == service.KIND_GAVE else "secondary",
            on_click=_set_mode, args=(service.KIND_GAVE,),
        )
    with got_col:
        st.button(
            "🟢 Paise mile", key="udhar_mode_got", use_container_width=True,
            type="primary" if mode == service.KIND_GOT else "secondary",
            on_click=_set_mode, args=(service.KIND_GOT,),
        )
    if mode in (service.KIND_GAVE, service.KIND_GOT):
        _render_entry_form(store_id, customer, mode)

    if balance > 0:
        message = service.reminder_message(get_current_store_name(), customer["name"], balance)
        st.link_button(
            "📲 WhatsApp reminder bhejo", service.whatsapp_url(customer["mobile"], message),
            use_container_width=True,
        )

    st.divider()
    history = _history(store_id, customer)
    if not history:
        st.info("Abhi koi entry nahi hai.")
        if st.button("🗑️ Ye customer hatao", key="udhar_delete_customer"):
            if service.delete_customer_if_unused(store_id, customer["customer_id"]):
                _refresh(store_id)
                _back()
                st.session_state[_FLASH] = ("success", "Customer hata diya gaya.")
                st.rerun()
        return
    for entry in history:
        _render_entry(store_id, entry)


def _render_entry_form(store_id: int, customer: dict, mode: str) -> None:
    with st.form(f"udhar_entry_form_{mode}", clear_on_submit=True):
        amount = st.number_input(
            "Amount ₹", min_value=0.0, step=1.0, value=None, placeholder="Kitne rupaye",
            format="%g",
        )
        note = st.text_input("Note (zaroori nahi)", placeholder="jaise: Dolo 2 strip")
        when = st.date_input("Tareekh", value=service.today_ist(), format="DD/MM/YYYY")
        label = "Udhar diya - Save" if mode == service.KIND_GAVE else "Paise mile - Save"
        submitted = st.form_submit_button(label, type="primary", use_container_width=True)
    if not submitted:
        return
    result = service.add_entry(store_id, customer["customer_id"], mode, amount, note, when)
    if result["status"] == "added":
        st.session_state[_MODE] = None
        _refresh(store_id)
        verb = "udhar likh diya" if mode == service.KIND_GAVE else "paise jama ho gaye"
        st.session_state[_FLASH] = ("success", f"✅ {service.money(result['amount'])} {verb}.")
        st.rerun(scope="fragment")
    elif result["status"] == "bad_amount":
        st.warning("Sahi amount likho (0 se zyada).")
    else:
        st.error("Entry save nahi hui.")


def _render_entry(store_id: int, entry: dict) -> None:
    gave = entry["kind"] == service.KIND_GAVE
    color = _RED if gave else _GREEN
    sign = "−" if gave else "+"
    title = "Udhar diya" if gave else "Paise mile"
    try:
        day = date.fromisoformat(str(entry["entry_date"])[:10]).strftime("%d %b %Y")
    except ValueError:
        day = str(entry["entry_date"])
    note = f"<div style='font-size:0.85rem; color:#888;'>{html.escape(str(entry['note']))}</div>" if entry.get("note") else ""
    with st.container(border=True, key=f"udhar_entry_{entry['entry_id']}"):
        text_col, delete_col = st.columns([5, 1], vertical_alignment="center")
        with text_col:
            st.markdown(
                f"<div style='display:flex; justify-content:space-between; gap:0.5rem;'>"
                f"<div><div style='font-weight:600;'>{title}</div>"
                f"<div style='font-size:0.8rem; color:#888;'>{day}</div>{note}</div>"
                f"<div style='text-align:right;'><div style='font-weight:700; color:{color};'>"
                f"{sign}{html.escape(service.money(entry['amount']))}</div>"
                f"<div style='font-size:0.8rem; color:#888;'>Baaki {html.escape(service.money(entry['balance_after']))}"
                f"{' (advance)' if entry['balance_after'] < 0 else ''}</div></div></div>",
                unsafe_allow_html=True,
            )
        with delete_col:
            st.button(
                "🗑️", key=f"udhar_del_{entry['entry_id']}", use_container_width=True,
                on_click=_ask_delete, args=(entry["entry_id"],),
            )
        if st.session_state.get(_CONFIRM) == entry["entry_id"]:
            st.caption("Ye entry pakka hatani hai?")
            yes_col, no_col = st.columns(2)
            with yes_col:
                st.button(
                    "Haan, hatao", key=f"udhar_yes_{entry['entry_id']}", type="primary",
                    use_container_width=True, on_click=_do_delete, args=(store_id, entry["entry_id"]),
                )
            with no_col:
                st.button("Nahi", key=f"udhar_no_{entry['entry_id']}", use_container_width=True, on_click=_cancel_delete)
