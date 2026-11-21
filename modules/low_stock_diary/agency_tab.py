"""
Low Stock -> "Agency" tab: each agency's "Mangwana hai" list.

The medicines the owner sent from the Diary to an agency. Per agency:
the thin lines (right slide = back to the Diary), a WhatsApp button with the
numbered message, copy, and "Order ho gaya" (clears that agency's list).

It shares the diary's session list, hidden-button swipe script and CSS, so it
is drawn after the Diary tab in the same run.
"""

import html

import streamlit as st

from core.cache_utils import get_cache_epoch
from core.session import get_current_store_id
from modules.low_stock_diary import service
from modules.low_stock_diary import ui as diary_ui

_FLASH = "lsa_flash"
_MOBILES = "lsa_mobiles"

_CSS = """
<style>
/* the buttons under an agency's list: side by side, also on a phone */
div[class*="st-key-lsa_btns_"] [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 0.5rem !important; }
div[class*="st-key-lsa_btns_"] [data-testid="stHorizontalBlock"] > * { min-width: 0 !important; flex: 1 1 0 !important; width: auto !important; }
div[class*="st-key-lsa_wa_"] a, div[class*="st-key-lsa_wa_"] button[kind="secondary"] { background: #25D366 !important; border-color: #25D366 !important; color: #fff !important;
                                 min-height: 2.8rem; font-weight: 700; }
div[class*="st-key-lsa_wa_"] a *, div[class*="st-key-lsa_wa_"] button[kind="secondary"] * { color: #fff !important; }
</style>
"""


def render_agency_tab() -> None:
    """The Agency tab. A problem here never breaks the other tabs."""
    try:
        st.markdown(_CSS, unsafe_allow_html=True)
        _render(get_current_store_id())
    except Exception as error:
        st.error("Agency list abhi nahi khul saki. " + str(error))


def _return_row(store_id: int, diary_id: int) -> None:
    """Right slide on a line: the medicine goes back to the plain Diary."""
    service.return_to_diary(store_id, [diary_id])
    for row in diary_ui._entries(store_id):
        if row["diary_id"] == diary_id:
            row["agency_id"] = None


def _order_done(store_id: int, agency_id: int, agency_name: str) -> None:
    count = service.clear_agency_list(store_id, agency_id)
    diary_ui._reload(store_id)
    st.session_state[_FLASH] = f"✅ {agency_name} ki list saaf ho gayi ({count} dawai)."


def _mobiles(store_id: int) -> dict:
    """The saved agency numbers: read once, kept in the session, changed only
    by _save_mobile (so this tab does not ask the database on every redraw)."""
    saved = st.session_state.get(_MOBILES)
    if saved is None or saved[0] != store_id:
        saved = (store_id, service.agency_mobiles(store_id))
        st.session_state[_MOBILES] = saved
    return saved[1]


def _save_mobile(store_id: int, agency_id: int, text: str) -> None:
    result = service.save_agency_mobile(store_id, agency_id, text)
    if result["status"] == "saved":
        _mobiles(store_id)[int(agency_id)] = result["mobile"]
        st.session_state[_FLASH] = "✅ Number save ho gaya. Ab WhatsApp reminder par tap karoge to seedhi chat khulegi."
    elif result["status"] == "bad_mobile":
        st.session_state[_FLASH] = "⚠️ Number sahi nahi hai - 10 digit ka mobile number daalo."
    else:
        st.session_state[_FLASH] = ("⚠️ Number save nahi ho paya. Ek baar database/agency_contacts.sql "
                                    "Supabase me chalani hogi.")


def _agency_names(store_id: int) -> dict:
    try:
        return dict(diary_ui._agency_names_cached(store_id, get_cache_epoch(store_id)))
    except Exception:
        return {}


def _render(store_id: int) -> None:
    flash = st.session_state.pop(_FLASH, None)
    if flash:
        (st.success if flash.startswith("✅") else st.warning)(flash)

    _, by_agency = service.split_rows(diary_ui._entries(store_id))
    if not by_agency:
        st.info("Abhi kisi agency ki list nahi hai. Diary me dawai par tap karke "
                "'Agency chuno' se yahan bhejo.")
        return

    names = _agency_names(store_id)
    mobiles = _mobiles(store_id)
    total = sum(len(rows) for rows in by_agency.values())
    st.caption(f"🏢 {len(by_agency)} agency  •  {total} dawai mangwani hai  •  dawai ko right slide karo = Diary me wapas")

    ordered = sorted(by_agency, key=lambda agency_id: str(names.get(agency_id, "")).lower())
    for agency_id in ordered:
        rows = list(reversed(by_agency[agency_id]))            # oldest first
        agency_name = names.get(agency_id) or f"Agency {agency_id}"
        with st.expander(f"🏢 {agency_name}  •  {len(rows)} dawai", expanded=False):      # closed every time the tab is opened
            _render_agency(store_id, agency_id, agency_name, rows, mobiles.get(agency_id))


def _render_agency(store_id: int, agency_id: int, agency_name: str, rows: list, mobile: str = None) -> None:
    st.markdown(
        "<div class='lsd-list'>"
        + "".join(
            f"<div class='lsd-row lsd-id-{int(row['diary_id'])}'>{html.escape(str(row['name']))}</div>"
            for row in rows
        )
        + "</div>",
        unsafe_allow_html=True,
    )
    # Hidden by the Diary's CSS: the right slide presses a line's button.
    for row in rows:
        st.button("↩", key=f"lsd_del_{row['diary_id']}", on_click=_return_row, args=(store_id, row["diary_id"]))

    message = service.order_message(agency_name, [row["name"] for row in rows])
    with st.container(key=f"lsa_wa_{agency_id}"):
        if mobile:
            # number known: the agency's own chat opens directly
            st.link_button("💬 WhatsApp reminder", service.whatsapp_url(message, mobile), use_container_width=True)
        else:
            # first time: ask the number once - or go on without it
            with st.popover("💬 WhatsApp reminder", use_container_width=True):
                st.caption("Agency ka WhatsApp number daalo, agli baar se seedhi uski chat khulegi.")
                number = st.text_input(
                    "Agency ka mobile number", key=f"lsa_num_{agency_id}", max_chars=15,
                    placeholder="10 digit number", label_visibility="collapsed",
                )
                st.button(
                    "💾 Number save karo", key=f"lsa_save_{agency_id}", type="primary",
                    use_container_width=True, on_click=_save_mobile, args=(store_id, agency_id, number),
                )
                st.link_button(
                    "Bina number ke aage badho", service.whatsapp_url(message), use_container_width=True,
                )
    with st.container(key=f"lsa_btns_{agency_id}"):
        copy_col, done_col = st.columns(2)
        with copy_col:
            with st.popover("📋 Copy karo", use_container_width=True):
                st.code(message, language=None)
        with done_col:
            with st.popover("✅ Order ho gaya", use_container_width=True):
                st.caption("Is agency ki poori list saaf ho jayegi.")
                st.button(
                    "Haan, list saaf karo", key=f"lsa_done_{agency_id}", type="primary",
                    on_click=_order_done, args=(store_id, agency_id, agency_name),
                )
    if mobile:
        with st.popover(f"📞 +91 {mobile}  (badlo)", use_container_width=True):
            number = st.text_input(
                "Naya number", key=f"lsa_edit_{agency_id}", max_chars=15,
                placeholder="10 digit number", label_visibility="collapsed",
            )
            st.button(
                "💾 Number badlo", key=f"lsa_change_{agency_id}", type="primary",
                use_container_width=True, on_click=_save_mobile, args=(store_id, agency_id, number),
            )