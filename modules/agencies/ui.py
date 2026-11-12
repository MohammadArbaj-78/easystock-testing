"""
Agencies screen UI.

Renders the ledger for every agency (distributor/wholesaler) this store
has scanned a bill from: a list of agencies with their running
balance, and - inside each agency's dropdown - its full bill history
(newest first) and a "Pay" form to record a payment..

No business logic, no SQL here - calls modules.agencies.service and
renders results. If a balance looks wrong, the bug is in
modules.agencies.service or modules.agencies.repository, never here.
"""

import streamlit as st

from modules.agencies import service as agencies_service
from core.session import get_current_store_id
from core.cache_utils import get_cache_epoch, bump_cache_epoch
import html

from core.supabase_storage import get_invoice_image_urls
# The medicine rows inside an agency are the Products screen's own rows
# (same summary line, same Edit / Delete) - reused, not copied.
from modules.products.ui import _render_product_row

try:
    from st_keyup import st_keyup
except ImportError:          # package not installed: a normal text box is used instead
    st_keyup = None

MEDICINES_PAGE_SIZE = 10
_KEYUP_DEBOUNCE_MS = 150

_CARD_CSS = """
<style>
/* Each agency is its own clearly outlined card. */
[class*="st-key-agency_card_"] {
    border: 2px solid var(--primary-color, #1f6f5b);
    border-radius: 0.75rem;
    padding: 0.35rem;
    margin-bottom: 0.9rem;
}
</style>
"""


@st.cache_data(ttl=840, show_spinner=False)
def _get_bill_image_urls_cached(image_paths: tuple) -> dict:
    """Signed urls (valid 15 min) for every bill photo, from one storage
    call - so opening a bill needs no further wait."""
    return get_invoice_image_urls(list(image_paths))


@st.cache_data(show_spinner=False)
def _get_all_agency_details_cached(store_id: int, _epoch: int) -> dict:
    return agencies_service.get_all_agency_details(store_id)


@st.cache_data(show_spinner=False)
def _get_agency_medicines_cached(store_id: int, _epoch: int) -> dict:
    return agencies_service.get_agency_medicines_by_agency(store_id)


@st.cache_data(show_spinner=False)
def _get_agency_ledger_cached(store_id: int, _epoch: int) -> list:
    return agencies_service.get_agency_ledger(store_id)


@st.cache_data(show_spinner=False)
def _get_agency_detail_cached(store_id: int, agency_id: int, _epoch: int) -> dict:
    return agencies_service.get_agency_detail(store_id, agency_id)


def render_agencies_page() -> None:
    """Render the Agencies (ledger) screen."""
    st.subheader("🏢 Agencies")

    store_id = get_current_store_id()
    agencies = _get_agency_ledger_cached(store_id, get_cache_epoch(store_id))

    if not agencies:
        st.info(
            "No agencies yet. Scanning and saving an invoice with an "
            "agency name will add one here automatically."
        )
        return

    st.markdown(_CARD_CSS, unsafe_allow_html=True)
    all_details = _get_all_agency_details_cached(store_id, get_cache_epoch(store_id))
    photo_paths = tuple(sorted({
        bill["image_path"]
        for detail in all_details.values()
        for bill in detail["bills"]
        if bill.get("image_path")
    }))
    image_urls = _get_bill_image_urls_cached(photo_paths) if photo_paths else {}

    total_balance = sum(agency["balance"] for agency in agencies)
    st.caption(f"Total outstanding across all agencies: ₹{total_balance:,.2f}")

    for agency in agencies:
        balance = agency["balance"]
        if balance > 0:
            balance_label = f"₹{balance:,.2f} baaki"
        elif balance < 0:
            balance_label = f"₹{-balance:,.2f} advance"
        else:
            balance_label = "Fully paid"

        with st.container(key=f"agency_card_{agency['agency_id']}"):
            with st.expander(f"{agency['agency_name']} — {balance_label}"):
                _render_agency_detail(store_id, agency, all_details.get(agency["agency_id"]), image_urls)


def _render_agency_detail(store_id: int, agency: dict, detail: dict = None, image_urls: dict = None) -> None:
    """Render one agency's dropdown: summary, Pay form, its medicines,
    then its bills. `detail` comes from ONE query for all agencies."""
    agency_id = agency["agency_id"]
    if detail is None:
        detail = {"bills": [], "payments": [], "total_billed": 0, "total_paid": 0, "balance": 0}

    summary_columns = st.columns(3)
    summary_columns[0].metric("Total billed", f"₹{detail['total_billed']:,.2f}")
    summary_columns[1].metric("Total paid", f"₹{detail['total_paid']:,.2f}")
    summary_columns[2].metric("Balance", f"₹{detail['balance']:,.2f}")

    _render_pay_form(store_id, agency_id)

    _render_medicines_section(store_id, agency_id)

    st.markdown("**Bills**")
    if not detail["bills"]:
        st.caption("No bills recorded yet.")
        return

    for bill in detail["bills"]:
        _render_bill_row(bill, image_urls or {})


def _render_medicines_section(store_id: int, agency_id: int) -> None:
    """The agency's medicines. Nothing is read or drawn until the switch
    is turned on, so opening the Agencies screen stays fast."""
    if not st.toggle("💊 Medicines", key=f"agency_meds_open_{agency_id}"):
        return
    _render_agency_medicines(store_id, agency_id)


def _load_more_medicines(limit_key: str) -> None:
    st.session_state[limit_key] = st.session_state.get(limit_key, MEDICINES_PAGE_SIZE) + MEDICINES_PAGE_SIZE


@st.fragment
def _render_agency_medicines(store_id: int, agency_id: int) -> None:
    """Live-search box + the agency's medicines, 10 at a time. A fragment,
    so typing in the search box redraws only this list."""
    search_key = f"agency_meds_search_{agency_id}"
    limit_key = f"agency_meds_limit_{agency_id}"
    last_key = f"agency_meds_last_{agency_id}"

    hint = "Dawai ka naam ya batch likho"
    if st_keyup is not None:
        try:
            term = st_keyup("Search medicine", placeholder=hint, debounce=_KEYUP_DEBOUNCE_MS,
                            key=search_key, label_visibility="collapsed")
        except TypeError:        # an older version without placeholder / label options
            term = st_keyup("Search medicine", debounce=_KEYUP_DEBOUNCE_MS, key=search_key)
    else:
        term = st.text_input("Search medicine", placeholder=hint, key=search_key,
                             label_visibility="collapsed")
    term = term or ""

    # A new search starts again from the first page.
    if st.session_state.get(last_key) != term:
        st.session_state[last_key] = term
        st.session_state[limit_key] = MEDICINES_PAGE_SIZE

    products = _get_agency_medicines_cached(store_id, get_cache_epoch(store_id)).get(agency_id, [])
    if not products:
        st.caption("Is agency ki koi medicine abhi stock me nahi hai.")
        return

    limit = st.session_state.get(limit_key, MEDICINES_PAGE_SIZE)
    page = agencies_service.search_agency_medicines(products, term, limit)
    if not page["items"]:
        st.info("No medicines match your search.")
        return

    st.caption(f"Showing {len(page['items'])} of {page['total']} medicine(s)")
    for product in page["items"]:
        _render_product_row(store_id, product)

    if page["total"] > len(page["items"]):
        st.button(
            f"⬇️ Load {min(MEDICINES_PAGE_SIZE, page['total'] - len(page['items']))} more",
            key=f"agency_meds_more_{agency_id}",
            use_container_width=True,
            on_click=_load_more_medicines,
            args=(limit_key,),
        )


def _render_bill_row(bill: dict, image_urls: dict = None) -> None:
    """Render one bill as a single expandable row - the date + total is
    the collapsed summary (same per-row-expander pattern as Products),
    and opening it reveals the photo, if this bill has one stored.
    Bills saved before the photo-storage feature existed simply have no
    image_path, so the expander just shows "No photo saved"."""
    label = bill["invoice_date"] or "(no date on bill)"
    summary = f"🧾 {label}  •  ₹{bill['grand_total']:,.2f}"

    with st.expander(summary):
        image_path = bill.get("image_path")
        if not image_path:
            st.caption("No photo saved for this bill.")
            return

        image_url = (image_urls or {}).get(image_path)
        if not image_url:
            st.caption("Could not load the photo right now. Please try again later.")
            return

        content_type = bill.get("image_content_type") or ""
        if content_type == "application/pdf":
            st.markdown(f"[Open bill PDF]({image_url})")
        else:
            # st.image()'s own fullscreen viewer doesn't support
            # pinch-zoom inside this app's embedded iframe on mobile -
            # a plain link opens the photo in the browser's OWN image
            # viewer (a new tab), where native pinch-zoom works fully.
            # loading="lazy": the browser downloads the photo only when this
            # bill is opened, not for every bill of every agency on load.
            st.markdown(
                f'<img src="{html.escape(image_url, quote=True)}" loading="lazy" '
                f'style="width:100%;border-radius:6px">',
                unsafe_allow_html=True,
            )
            st.markdown(f"[🔍 Open full-size photo (pinch-to-zoom)]({image_url})")

def _render_pay_form(store_id: int, agency_id: int) -> None:
    """Render the amount/date inputs and "Pay" button for one agency."""
    amount_key = f"agency_pay_amount_{agency_id}"
    date_key = f"agency_pay_date_{agency_id}"
    clear_flag_key = f"_clear_{amount_key}"

    # A widget's own session_state value cannot be changed by code AFTER
    # that widget has already been rendered in this run (Streamlit
    # raises StreamlitWidgetAlreadyInstantiatedError). So clearing the
    # amount box after a successful payment happens here, BEFORE the
    # text_input below is created - a flag set on the previous run
    # (right after recording the payment) is checked and acted on now.
    if st.session_state.pop(clear_flag_key, False):
        st.session_state[amount_key] = ""

    amount_col, date_col, button_col = st.columns([2, 2, 1])
    with amount_col:
        amount_text = st.text_input("Amount paid (₹)", key=amount_key, placeholder="e.g. 4000")
    with date_col:
        paid_on = st.date_input("Paid on", key=date_key)
    with button_col:
        st.write("")
        pay_clicked = st.button("💰 Pay", key=f"agency_pay_button_{agency_id}", use_container_width=True)

    if pay_clicked:
        outcome = agencies_service.record_payment(
            store_id, agency_id, amount_text, str(paid_on)
        )
        if outcome["recorded"]:
            bump_cache_epoch(store_id)
            st.session_state[clear_flag_key] = True
            st.success(f"₹{outcome['amount']:,.2f} payment recorded.")
            st.rerun()
        else:
            st.error(outcome["reason"])