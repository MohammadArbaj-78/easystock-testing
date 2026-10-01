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
from core.supabase_storage import get_invoice_image_url

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
    agencies = _get_agency_ledger_cached(store_id, get_cache_epoch())

    if not agencies:
        st.info(
            "No agencies yet. Scanning and saving an invoice with an "
            "agency name will add one here automatically."
        )
        return

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

        with st.expander(f"{agency['agency_name']} — {balance_label}"):
            _render_agency_detail(store_id, agency)


def _render_agency_detail(store_id: int, agency: dict) -> None:
    """Render one agency's dropdown: summary, Pay form, then its bills."""
    agency_id = agency["agency_id"]
    detail = _get_agency_detail_cached(store_id, agency_id, get_cache_epoch())

    summary_columns = st.columns(3)
    summary_columns[0].metric("Total billed", f"₹{detail['total_billed']:,.2f}")
    summary_columns[1].metric("Total paid", f"₹{detail['total_paid']:,.2f}")
    summary_columns[2].metric("Balance", f"₹{detail['balance']:,.2f}")

    _render_pay_form(store_id, agency_id)

    st.markdown("**Bills**")
    if not detail["bills"]:
        st.caption("No bills recorded yet.")
        return

    for bill in detail["bills"]:
        _render_bill_row(bill)


def _render_bill_row(bill: dict) -> None:
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

        image_url = get_invoice_image_url(image_path)
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
            st.image(image_url)
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
            bump_cache_epoch()
            st.session_state[clear_flag_key] = True
            st.success(f"₹{outcome['amount']:,.2f} payment recorded.")
            st.rerun()
        else:
            st.error(outcome["reason"])