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
from modules.agencies import service as agencies_service
from modules.sales import service as sales_service

try:
    from st_keyup import st_keyup
except ImportError:          # package not installed: a normal text box is used instead
    st_keyup = None

_STATE = "lsd_state"
_VERSION = "lsd_search_version"
_FLASH = "lsd_flash"
_SELECTED = "lsd_selected"
_AGENCY_PICK = "lsd_agency_pick"
_NAMES = "lsd_store_names"
_NAMES_MAX_AGE_SECONDS = 600
_KEYUP_DEBOUNCE_MS = 120

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
    """Thin diary lines (own simple styling, no empty space) and the hidden remove buttons."""
    st.markdown(
        """
        <style>
        .lsd-list { display: flex; flex-direction: column; gap: 0.3rem; margin: 0.2rem 0 0.4rem 0; }
        .lsd-row {
            border: 1px solid rgba(49, 51, 63, 0.2);
            border-radius: 0.5rem;
            padding: 0.45rem 0.75rem;
            font-size: 1rem; font-weight: 600; line-height: 1.35;
            touch-action: pan-y;
            overflow-wrap: anywhere;
        }
        .lsd-row.lsd-sel {
            border-color: var(--primary-color, #1f6f5b);
            background: rgba(31, 111, 91, 0.12);
        }
        .lsd-row.lsd-sel::before { content: "\\2713  "; color: var(--primary-color, #1f6f5b); }
        div[class*="st-key-lsd_del_"], div[class*="st-key-lsd_sel_"] { display: none !important; }
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
                if (window.__easystockDiarySwipeV3) { return; }
                window.__easystockDiarySwipeV3 = true;
                var drag = null;

                function boxOf(card) { return card; }
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
                    var card = e.target.closest('.lsd-row');
                    if (!card) { return; }
                    var found = /lsd-id-(\\d+)/.exec(String(card.className));
                    var rowId = found ? parseInt(found[1], 10) : NaN;
                    if (isNaN(rowId)) { return; }
                    drag = {
                        id: rowId, box: boxOf(card), x: e.clientX, y: e.clientY,
                        t: Date.now(), dx: 0, active: false, moved: 0,
                        main: document.querySelector('[data-testid="stMain"]'), mainOverflow: ""
                    };
                }, true);

                document.addEventListener("pointermove", function (e) {
                    if (!drag) { return; }
                    var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
                    drag.moved = Math.max(drag.moved, Math.abs(dx), Math.abs(dy));
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
                    if (!d.active) {
                        // A plain tap (no real movement) selects / unselects the line.
                        if (!cancelled && d.moved < 10 && Date.now() - d.t < 700) {
                            var pick = document.querySelector(".st-key-lsd_sel_" + d.id + " button");
                            if (pick) { pick.click(); }
                        }
                        return;
                    }
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
    """One tap = one database write. The diary list is already in the session,
    so nothing is read first (the database itself refuses a duplicate) and the
    new line is put on top of the list directly."""
    rows = _entries(store_id)
    result = service.add_medicine(store_id, name, known_rows=rows)
    if result["status"] == "added":
        rows.insert(0, {"diary_id": result["diary_id"], "name": result["name"], "agency_id": None})
        st.session_state[_FLASH] = ("success", f"✅ {result['name']} diary me jud gayi.")
    elif result["status"] == "exists":
        st.session_state[_FLASH] = ("info", f"{result['name']} pehle se diary me hai.")
    else:
        st.session_state[_FLASH] = ("warning", "Dawai ka naam kam se kam 3 akshar ka likho.")
    st.session_state[_VERSION] = st.session_state.get(_VERSION, 0) + 1     # empty search box again


def _delete(store_id: int, diary_id: int) -> None:
    service.remove_medicines(store_id, [diary_id])
    st.session_state.get(_SELECTED, set()).discard(diary_id)
    state = st.session_state.get(_STATE)
    if state is not None and state["store_id"] == store_id:
        state["rows"] = [row for row in state["rows"] if row["diary_id"] != diary_id]


def _toggle(diary_id: int) -> None:
    chosen = st.session_state.setdefault(_SELECTED, set())
    if diary_id in chosen:
        chosen.discard(diary_id)
    else:
        chosen.add(diary_id)


@st.cache_data(show_spinner=False, ttl=300)
def _agency_names_cached(store_id: int, _epoch: int) -> list:
    """[(agency_id, agency_name)] - only the names are used here."""
    return [(a["agency_id"], a["agency_name"]) for a in agencies_service.get_agency_ledger(store_id)]


def _send_to_agency(store_id: int, agency_id, agency_name: str, ids: list) -> None:
    service.assign_to_agency(store_id, ids, agency_id)
    state = st.session_state.get(_STATE)
    if state is not None and state["store_id"] == store_id:
        for row in state["rows"]:
            if row["diary_id"] in ids:
                row["agency_id"] = agency_id
    st.session_state[_SELECTED] = set()
    st.session_state[_AGENCY_PICK] = st.session_state.get(_AGENCY_PICK, 0) + 1
    st.session_state[_FLASH] = ("success", f"✅ {len(ids)} dawai {agency_name} ki 'Mangwana hai' list me gayi.")


def _clear_selection() -> None:
    st.session_state[_SELECTED] = set()


def _render_send_bar(store_id: int, ids: list) -> None:
    """Shown only while medicines are selected: pick an agency, send them there."""
    agencies = _agency_names_cached(store_id, get_cache_epoch(store_id))
    st.markdown(f"**{len(ids)} dawai chuni**")
    if not agencies:
        st.caption("Abhi koi agency nahi hai. Pehle kisi agency ka bill scan karke save karo.")
    else:
        names = dict(agencies)
        pick = st.selectbox(
            "Agency chuno", options=[agency_id for agency_id, _ in agencies],
            format_func=lambda agency_id: names[agency_id], index=None,
            placeholder="Agency chuno (chunte hi list me jayegi)", label_visibility="collapsed",
            key=f"lsd_agency_{st.session_state.get(_AGENCY_PICK, 0)}",
        )
        if pick is not None:        # choosing the agency sends the medicines right away
            _send_to_agency(store_id, pick, names.get(pick, ""), ids)
            st.rerun()               # the whole page: the Agency tab shows the new list too
    st.button("Chunav hatao", key="lsd_unselect", on_click=_clear_selection)


def _tile(label: str, key: str, store_id: int, name: str) -> None:
    st.button(label, key=key, use_container_width=True, on_click=_add, args=(store_id, name))


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
    plain, _ = service.split_rows(rows)
    if not plain:
        st.info("Diary khali hai. Upar dawai ka naam likhkar jodo.")
        return
    chosen = st.session_state.setdefault(_SELECTED, set())
    chosen &= {row["diary_id"] for row in plain}
    st.caption(f"📒 {len(plain)} dawai  •  tap = chuno  •  right slide = hatao")
    if chosen:
        _render_send_bar(store_id, sorted(chosen))
    st.markdown(
        "<div class='lsd-list'>"
        + "".join(
            f"<div class='lsd-row lsd-id-{int(row['diary_id'])}"
            f"{' lsd-sel' if row['diary_id'] in chosen else ''}'>{html.escape(str(row['name']))}</div>"
            for row in plain
        )
        + "</div>",
        unsafe_allow_html=True,
    )
    # Hidden by CSS: the gestures press these (removal / selection are the
    # normal Python callbacks _delete / _toggle).
    for row in plain:
        st.button("✖", key=f"lsd_del_{row['diary_id']}", on_click=_delete, args=(store_id, row["diary_id"]))
        st.button("✔", key=f"lsd_sel_{row['diary_id']}", on_click=_toggle, args=(row["diary_id"],))


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