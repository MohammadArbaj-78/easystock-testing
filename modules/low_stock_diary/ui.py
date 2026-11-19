"""
Low Stock Diary screen (a tab of the Low Stock page).

Search a medicine, tap it (or add the typed name) and it goes into the diary
list; the list stays until the owner deletes a medicine. No business logic
here - modules.low_stock_diary.service does that.
"""

import html
import time

import streamlit as st
import streamlit.components.v1 as components

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
        _inject_css()
        _inject_swipe_script()
        _render_diary(get_current_store_id())
    except Exception as error:
        st.error(_TABLE_HELP + str(error))


def _inject_css() -> None:
    """Thin diary lines (no empty space) and the hidden remove button."""
    st.markdown(
        """
        <style>
        div[class*="st-key-lsd_row_"] {
            padding: 0.4rem 0.75rem !important;
            touch-action: pan-y;
        }
        div[class*="st-key-lsd_row_"] [data-testid="stVerticalBlock"] {
            gap: 0 !important;
        }
        div[class*="st-key-lsd_del_"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _inject_swipe_script() -> None:
    """Swipe a diary line to the RIGHT (finger on a phone, mouse drag on a PC)
    to remove it. The line FOLLOWS the finger and fades while it moves; let go
    past a third of the width (or with a quick flick) and it flies off to the
    right, otherwise it springs back. Streamlit has no swipe gesture, so this
    small script only DRAGS the line and presses that line's own hidden remove
    button - the removal itself is the normal Python callback _delete. It fails
    silently if the page structure is not found, and installs itself once per
    browser tab."""
    components.html(
        """
        <script>
        try {
            var run = function () {
                if (window.__easystockDiarySwipeV1) { return; }
                window.__easystockDiarySwipeV1 = true;
                var drag = null;

                function boxOf(card) {
                    return card.closest('[data-testid="stVerticalBlockBorderWrapper"]') || card;
                }
                function restore(box, animate) {
                    box.style.transition = animate ? "transform 0.2s ease-out, opacity 0.2s ease-out" : "none";
                    box.style.transform = "";
                    box.style.opacity = "";
                    box.style.willChange = "";
                    box.style.userSelect = "";
                }

                document.addEventListener("pointerdown", function (e) {
                    if (e.pointerType === "mouse" && e.button !== 0) { return; }
                    if (e.target.closest("button, input, textarea, label, a")) { return; }
                    var card = e.target.closest('[class*="st-key-lsd_row_"]');
                    if (!card) { return; }
                    var idPart = String(card.className).split("st-key-lsd_row_")[1];
                    var rowId = idPart ? parseInt(idPart, 10) : NaN;
                    if (isNaN(rowId)) { return; }
                    drag = {
                        id: rowId, box: boxOf(card), x: e.clientX, y: e.clientY,
                        t: Date.now(), dx: 0, active: false,
                        main: document.querySelector('[data-testid="stMain"]'), mainOverflow: ""
                    };
                }, true);

                document.addEventListener("pointermove", function (e) {
                    if (!drag) { return; }
                    var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
                    if (!drag.active) {
                        if (Math.abs(dy) > 14 && Math.abs(dy) > Math.abs(dx)) { drag = null; return; }   // it is a scroll
                        if (!(dx > 8 && dx > Math.abs(dy))) { return; }
                        drag.active = true;
                        if (drag.main) {
                            drag.mainOverflow = drag.main.style.overflowX;
                            drag.main.style.overflowX = "hidden";
                        }
                        drag.box.style.transition = "none";
                        drag.box.style.willChange = "transform";
                        drag.box.style.userSelect = "none";
                    }
                    drag.dx = Math.max(0, dx);
                    var width = drag.box.offsetWidth || 300;
                    drag.box.style.transform = "translateX(" + drag.dx + "px)";
                    drag.box.style.opacity = String(Math.max(0.25, 1 - drag.dx / (width * 1.1)));
                    if (e.cancelable) { e.preventDefault(); }
                }, true);

                function finish(cancelled) {
                    if (!drag) { return; }
                    var d = drag;
                    drag = null;
                    if (!d.active) { return; }
                    var width = d.box.offsetWidth || 300;
                    var speed = d.dx / Math.max(1, Date.now() - d.t);           // pixels per millisecond
                    var remove = !cancelled && (d.dx > Math.max(70, width * 0.3) || (d.dx > 40 && speed > 0.6));
                    if (!remove) {
                        restore(d.box, true);
                        setTimeout(function () { if (d.main) { d.main.style.overflowX = d.mainOverflow; } }, 250);
                        return;
                    }
                    d.box.style.transition = "transform 0.16s ease-out, opacity 0.16s ease-out";
                    d.box.style.transform = "translateX(" + (width + 40) + "px)";
                    d.box.style.opacity = "0";
                    var button = document.querySelector(".st-key-lsd_del_" + d.id + " button");
                    if (button) { button.click(); }                              // the real removal starts at once
                    // When the line is really gone from the page (or after 3 s),
                    // clear the styles: the page may reuse this same box.
                    var tries = 0;
                    var timer = setInterval(function () {
                        tries += 1;
                        var stillThere = document.querySelector(".st-key-lsd_del_" + d.id + " button");
                        if (!stillThere || tries > 30) {
                            clearInterval(timer);
                            restore(d.box, false);
                            if (d.main) { d.main.style.overflowX = d.mainOverflow; }
                        }
                    }, 100);
                }
                document.addEventListener("pointerup", function () { finish(false); }, true);
                document.addEventListener("pointercancel", function () { finish(true); }, true);
            };
            var bridge = window.parent.document.createElement("script");
            bridge.textContent = "(" + run.toString() + ")();";
            window.parent.document.body.appendChild(bridge);
        } catch (e) { /* best effort - without it the list still shows */ }
        </script>
        """,
        height=0,
    )


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
    st.caption(f"📒 {len(rows)} dawai  •  hatane ke liye dawai ko right slide karo")
    for row in rows:
        with st.container(border=True, key=f"lsd_row_{row['diary_id']}"):
            st.markdown(
                f"<div style='font-size:1rem; font-weight:600; line-height:1.3;'>{html.escape(str(row['name']))}</div>",
                unsafe_allow_html=True,
            )
            # Hidden by CSS: the swipe gesture presses it (the removal itself is
            # the normal Python callback _delete).
            st.button("✖", key=f"lsd_del_{row['diary_id']}", on_click=_delete, args=(store_id, row["diary_id"]))


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