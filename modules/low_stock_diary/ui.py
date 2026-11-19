"""
Low Stock Diary screen (a tab of the Low Stock page).

Search a medicine, tap it (or add the typed name) and it goes into the diary
list; the list stays until the owner deletes a medicine. No business logic
here - modules.low_stock_diary.service does that.
"""

import html
import time

import streamlit as st

from core.cache_utils import get_cache_epoch
from core.session import get_current_store_id
from modules.low_stock_diary import service
from modules.sales import service as sales_service

try:
    from st_keyup import st_keyup
except ImportError:          # package not installed: a normal text box is used instead
    st_keyup = None

_STATE = "lsd_state"
_VERSION = "lsd_search_version"
_FLASH = "lsd_flash"
_NAMES = "lsd_store_names"
_NAMES_MAX_AGE_SECONDS = 120
_KEYUP_DEBOUNCE_MS = 150

_TABLE_HELP = (
    "Diary abhi shuru nahi ho saki. Supabase me `database/low_stock_diary.sql` "
    "ek baar chalani hai. Detail: "
)


def render_low_stock_diary() -> None:
    """The Diary tab. A problem here (e.g. the table is not created yet) is
    shown as a message and never breaks the Alerts tab."""
    try:
        _render_diary(get_current_store_id())
    except Exception as error:
        st.error(_TABLE_HELP + str(error))


def _entries(store_id: int) -> list:
    """The diary list: read once, kept in the session, read again only after
    this screen changes it (or for another store)."""
    state = st.session_state.get(_STATE)
    if state is None or state["store_id"] != store_id:
        state = {"store_id": store_id, "rows": service.get_entries(store_id)}
        st.session_state[_STATE] = state
    return state["rows"]


def _reload(store_id: int) -> None:
    st.session_state[_STATE] = {"store_id": store_id, "rows": service.get_entries(store_id)}


def _store_names(store_id: int) -> list:
    """The store's medicine names (for suggestions), read only when the owner
    starts typing, then kept for 2 minutes / until stock changes."""
    epoch = get_cache_epoch(store_id)
    saved = st.session_state.get(_NAMES)
    if (
        saved is not None and saved["store_id"] == store_id and saved["epoch"] == epoch
        and time.monotonic() - saved["at"] < _NAMES_MAX_AGE_SECONDS
    ):
        return saved["names"]
    names = service.store_medicine_names(sales_service.get_store_catalog(store_id))
    st.session_state[_NAMES] = {"store_id": store_id, "epoch": epoch, "names": names, "at": time.monotonic()}
    return names


@st.cache_data(show_spinner=False, ttl=300)
def _outside_cached(term: str) -> dict:
    return service.suggest(term, [])


def _search_box() -> str:
    key = f"lsd_search_{st.session_state.get(_VERSION, 0)}"
    hint = "Dawai ka naam likho (jaise Dolo)"
    if st_keyup is not None:
        try:
            text = st_keyup(
                "Search medicine", placeholder=hint, debounce=_KEYUP_DEBOUNCE_MS,
                key=key, label_visibility="collapsed",
            )
        except TypeError:
            text = st_keyup("Search medicine", debounce=_KEYUP_DEBOUNCE_MS, key=key)
        return text or ""
    text = st.text_input("Search medicine", placeholder=hint, key=key, label_visibility="collapsed")
    st.button("🔎 Search", key="lsd_search_button", use_container_width=True)
    return text or ""


def _stock_text(quantity) -> str:
    return f"{quantity:g}"


def _add(store_id: int, name: str) -> None:
    result = service.add_medicine(store_id, name)
    if result["status"] == "added":
        st.session_state[_FLASH] = ("success", f"✅ {result['name']} diary me jud gayi.")
    elif result["status"] == "exists":
        st.session_state[_FLASH] = ("info", f"{result['name']} pehle se diary me hai.")
    else:
        st.session_state[_FLASH] = ("warning", "Dawai ka naam kam se kam 3 akshar ka likho.")
    _reload(store_id)
    st.session_state[_VERSION] = st.session_state.get(_VERSION, 0) + 1     # empty search box again


def _delete(store_id: int, diary_id: int) -> None:
    service.remove_medicines(store_id, [diary_id])
    _reload(store_id)


def _tile(label: str, key: str, store_id: int, name: str) -> None:
    if st.button(label, key=key, use_container_width=True):
        _add(store_id, name)
        st.rerun(scope="fragment")


@st.fragment
def _render_diary(store_id: int) -> None:
    """A fragment: typing and every button redraw only this tab."""
    rows = _entries(store_id)

    flash = st.session_state.pop(_FLASH, None)
    if flash:
        getattr(st, flash[0])(flash[1])

    term = _search_box().strip()
    if term:
        result = _store_result(store_id, term)
        _render_suggestions(store_id, result)

    st.divider()
    if not rows:
        st.info("Diary khali hai. Upar dawai ka naam likhkar jodo.")
        return
    st.caption(f"📒 {len(rows)} dawai")
    for row in rows:
        with st.container(border=True, key=f"lsd_row_{row['diary_id']}"):
            name_col, delete_col = st.columns([5, 1], vertical_alignment="center")
            with name_col:
                st.markdown(
                    f"<div style='font-size:1.05rem; font-weight:600;'>{html.escape(str(row['name']))}</div>",
                    unsafe_allow_html=True,
                )
            with delete_col:
                st.button(
                    "🗑️", key=f"lsd_del_{row['diary_id']}", use_container_width=True,
                    on_click=_delete, args=(store_id, row["diary_id"]),
                )


def _store_result(store_id: int, term: str) -> dict:
    """The store's own medicines first (from memory); only if there is none,
    the medicine list (cached); only if that has none either, "add what you typed"."""
    result = service.suggest_from_store(term, _store_names(store_id))
    if result is not None:
        return result
    return _outside_cached(term)


def _render_suggestions(store_id: int, result: dict) -> None:
    kind = result["kind"]
    if kind == "store":
        for index, item in enumerate(result["items"]):
            label = f"**{item['name']}**\nStock: {_stock_text(item['quantity'])}"
            _tile(label, f"lsd_add_store_{index}", store_id, item["name"])
    elif kind == "master":
        for index, medicine in enumerate(result["items"]):
            detail = medicine.get("composition") or ""
            label = f"**{medicine['name']}**\n{detail}" if detail else f"**{medicine['name']}**"
            _tile(label, f"lsd_add_master_{index}", store_id, medicine["name"])
    elif kind == "new":
        _tile(f"➕ Add \"{result['name']}\"", "lsd_add_new", store_id, result["name"])
    else:
        st.info("Koi dawai nahi mili.")
