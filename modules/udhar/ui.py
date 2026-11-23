"""
Udhar Khata screen: customers who take medicines on credit.

Khatabook-like and made for few taps:
  list of customers (white rows: name + what is owed) -> tap a customer ->
  two big buttons "Udhar diya" / "Paise mile", reminder, thin history lines
  (right slide = delete). The phone's Back button goes one step at a time
  (entry form -> customer -> customer list -> previous page).

No business logic here - modules.udhar.service does that.
"""

import html
from datetime import date

import streamlit as st
import streamlit.components.v1 as components

from core import pdf_export
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
_FRESH = "udhar_fresh"            # the page was just opened (not a rerun of it)
_LIMIT = "udhar_limit"            # customers shown in the list
_LAST_TERM = "udhar_last_term"
_HLIMIT = "udhar_history_limit"   # history lines shown
_NC_NAME_V = "udhar_nc_name_v"    # new-customer boxes: a new number = an emptied box
_NC_MOBILE_V = "udhar_nc_mobile_v"
_NC_OPEN = "udhar_nc_open"
_KEYUP_DEBOUNCE_MS = 150
PAGE_SIZE = 30
HISTORY_PAGE_SIZE = 40
_RED = "#D32F2F"
_GREEN = "#2E7D32"
_AVATAR_COLORS = ("#1F6F5B", "#C2410C", "#6D28D9", "#0369A1", "#BE185D", "#4D7C0F", "#B45309")

_TABLE_HELP = (
    "Udhar Khata abhi shuru nahi ho saka. Supabase me `database/udhar_khata.sql` "
    "ek baar chalani hai. Detail: "
)

_CSS = """
<style>
/* summary tiles */
.ud-tiles { display: flex; gap: 0.5rem; margin: 0.2rem 0 0.6rem 0; }
.ud-tile { flex: 1; min-width: 0; background: #fff; border: 1px solid rgba(49,51,63,0.16);
           border-radius: 0.6rem; padding: 0.5rem 0.75rem; }
.ud-tl { font-size: 0.78rem; color: #777; }
.ud-tv { font-size: 1.4rem; font-weight: 800; line-height: 1.25; }
/* customer rows: white blocks, thin */
.ud-list { display: flex; flex-direction: column; gap: 0.35rem; margin: 0.3rem 0 0.4rem 0; }
.ud-row { display: flex; align-items: center; gap: 0.7rem; background: #fff;
          border: 1px solid rgba(49,51,63,0.12); border-radius: 0.6rem; padding: 0.5rem 0.75rem;
          cursor: pointer; user-select: none; -webkit-tap-highlight-color: rgba(0,0,0,0.06); }
.ud-av { width: 2.2rem; height: 2.2rem; border-radius: 50%; color: #fff; font-weight: 700;
         display: flex; align-items: center; justify-content: center; flex: none; }
.ud-name { flex: 1; min-width: 0; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ud-amt { text-align: right; flex: none; line-height: 1.25; }
.ud-amt b { font-size: 1rem; }
.ud-amt small { display: block; font-size: 0.72rem; color: #888; }
/* history lines: white, thin */
.ud-entry { background: #fff; border: 1px solid rgba(49,51,63,0.12); border-radius: 0.6rem;
            padding: 0.4rem 0.75rem; touch-action: pan-y; user-select: none; }
.ud-main { display: flex; justify-content: space-between; align-items: center; gap: 0.6rem; }
.ud-d { font-weight: 600; font-size: 0.95rem; line-height: 1.3; }
.ud-n { font-size: 0.78rem; color: #777; overflow-wrap: anywhere; line-height: 1.3; }
.ud-r { text-align: right; flex: none; line-height: 1.3; }
.ud-a { font-weight: 700; }
.ud-b { font-size: 0.75rem; color: #777; }
.ud-ask { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.35rem; padding-top: 0.35rem;
          border-top: 1px dashed rgba(49,51,63,0.25); font-size: 0.85rem; }
.ud-q { flex: 1; }
.ud-yes, .ud-no { padding: 0.3rem 0.7rem; border-radius: 0.4rem; font-weight: 600; cursor: pointer; }
.ud-yes { background: #D32F2F; color: #fff; }
.ud-no { border: 1px solid rgba(49,51,63,0.3); }
/* Udhar diya / Paise mile: two filled buttons side by side, also on a phone */
.st-key-udhar_actions [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 0.5rem !important; }
.st-key-udhar_actions [data-testid="stHorizontalBlock"] > * { min-width: 0 !important; flex: 1 1 0 !important; width: auto !important; }
.st-key-udhar_mode_gave button, .st-key-udhar_save_gave button { background: #D32F2F !important; border-color: #D32F2F !important; color: #fff !important; }
.st-key-udhar_mode_got button, .st-key-udhar_save_got button { background: #2E7D32 !important; border-color: #2E7D32 !important; color: #fff !important; }
.st-key-udhar_mode_gave button, .st-key-udhar_mode_got button { min-height: 3rem; font-weight: 700; }
.st-key-udhar_mode_gave button *, .st-key-udhar_mode_got button *, .st-key-udhar_save_gave button *, .st-key-udhar_save_got button * { color: #fff !important; }
/* reminder bar: fixed at the bottom of the screen, only the list scrolls */
/* it floats ABOVE Streamlit's own "Manage app" / app badge at the bottom corner (about 3.2rem tall) */
.st-key-udhar_bar { position: fixed; left: 0.5rem; right: 0.5rem; bottom: 3.8rem; max-width: 45rem; margin: 0 auto; z-index: 999;
                    background: #fff; border: 1px solid rgba(49,51,63,0.15); border-radius: 0.8rem;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.12); padding: 0.5rem; }
.st-key-udhar_bar [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 0.5rem !important; }
.st-key-udhar_bar [data-testid="stHorizontalBlock"] > * { min-width: 0 !important; flex: 1 1 0 !important; width: auto !important; }
.st-key-udhar_wa a { background: #25D366 !important; border-color: #25D366 !important; color: #fff !important; }
.st-key-udhar_sms a { background: #1E88E5 !important; border-color: #1E88E5 !important; color: #fff !important; }
.st-key-udhar_wa a, .st-key-udhar_sms a { min-height: 3rem; font-weight: 700; font-size: 0.82rem; white-space: nowrap; padding-left: 0.3rem !important; padding-right: 0.3rem !important; }
.st-key-udhar_wa a *, .st-key-udhar_sms a * { color: #fff !important; }
/* no "Press Enter to submit form" text inside the boxes */
.st-key-udhar_form_box [data-testid="InputInstructions"],
.st-key-udhar_entry_box_gave [data-testid="InputInstructions"],
.st-key-udhar_entry_box_got [data-testid="InputInstructions"] { display: none !important; }
/* buttons that only the gestures / the phone's Back button press */
div[class*="st-key-udhar_open_"], div[class*="st-key-udhar_del_"], div[class*="st-key-udhar_yes_"],
div[class*="st-key-udhar_no_"], .st-key-udhar_nav_back { display: none !important; }
</style>
<div class="ud-page" style="display:none"></div>
"""

# Runs in the page itself (installed once per browser tab, fails silently):
#  - tap a customer row / "Haan" / "Nahi"  -> presses that row's own hidden button
#  - slide a history line to the right    -> presses its hidden "delete?" button
#  - number keypad for the mobile / amount boxes
#  - a right swipe on a history line must not open the sidebar
_BEHAVIOUR_JS = """
<script>
try {
    var run = function () {
        if (window.__easystockUdharV1) { return; }
        window.__easystockUdharV1 = true;
        var drag = null;

        function idOf(el) {
            var found = /ud-id-(\\d+)/.exec(String(el.className));
            return found ? parseInt(found[1], 10) : NaN;
        }
        function press(selector) {
            var button = document.querySelector(selector + " button");
            if (button) { button.click(); }
        }
        function restore(box, animate) {
            box.style.transition = animate ? "transform 0.2s ease-out, opacity 0.2s ease-out" : "none";
            box.style.transform = "";
            box.style.opacity = "";
            box.style.willChange = "";
        }

        document.addEventListener("pointerdown", function (e) {
            if (e.pointerType === "mouse" && e.button !== 0) { return; }
            var box = e.target.closest(".ud-row, .ud-entry");
            if (!box) { return; }
            var id = idOf(box);
            if (isNaN(id)) { return; }
            drag = {
                box: box, id: id, entry: box.classList.contains("ud-entry"),
                act: e.target.closest(".ud-yes, .ud-no"),
                x: e.clientX, y: e.clientY, t: Date.now(), dx: 0, moved: 0, active: false,
                main: document.querySelector('[data-testid="stMain"]'), mainOverflow: ""
            };
        }, true);

        document.addEventListener("pointermove", function (e) {
            if (!drag) { return; }
            var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
            drag.moved = Math.max(drag.moved, Math.abs(dx), Math.abs(dy));
            if (!drag.entry) {
                if (Math.abs(dy) > 14) { drag = null; }                   // it is a scroll
                return;
            }
            if (!drag.active) {
                if (Math.abs(dy) > 14 && Math.abs(dy) > Math.abs(dx)) { drag = null; return; }
                if (!(dx > 8 && dx > Math.abs(dy))) { return; }
                drag.active = true;
                if (drag.main) {
                    drag.mainOverflow = drag.main.style.overflowX;
                    drag.main.style.overflowX = "hidden";
                }
                drag.box.style.transition = "none";
                drag.box.style.willChange = "transform";
            }
            drag.dx = Math.max(0, dx);
            var width = drag.box.offsetWidth || 300;
            drag.box.style.transform = "translateX(" + drag.dx + "px)";
            drag.box.style.opacity = String(Math.max(0.3, 1 - drag.dx / (width * 1.1)));
            if (e.cancelable) { e.preventDefault(); }
        }, true);

        function finish(cancelled) {
            if (!drag) { return; }
            var d = drag;
            drag = null;
            if (!d.active) {
                if (!cancelled && d.moved < 10 && Date.now() - d.t < 700) {       // a plain tap
                    if (d.act) {
                        press(d.act.classList.contains("ud-yes") ? ".st-key-udhar_yes_" + d.id : ".st-key-udhar_no_" + d.id);
                    } else if (!d.entry) {
                        if (window.__easystockUdharNav) { window.__easystockUdharNav.push(1); }
                        press(".st-key-udhar_open_" + d.id);
                    }
                }
                return;
            }
            var width = d.box.offsetWidth || 300;
            var speed = d.dx / Math.max(1, Date.now() - d.t);
            var ask = !cancelled && (d.dx > Math.max(70, width * 0.3) || (d.dx > 40 && speed > 0.6));
            restore(d.box, true);                                  // the line springs back; the question is asked under it
            setTimeout(function () { if (d.main) { d.main.style.overflowX = d.mainOverflow; } }, 250);
            if (ask) { press(".st-key-udhar_del_" + d.id); }
        }
        document.addEventListener("pointerup", function () { finish(false); }, true);
        document.addEventListener("pointercancel", function () { finish(true); }, true);

        // Opening the entry form is one Back step too: note it at the moment of the tap.
        document.addEventListener("click", function (e) {
            var nav = window.__easystockUdharNav;
            if (nav && e.target.closest && e.target.closest(".st-key-udhar_mode_gave button, .st-key-udhar_mode_got button")
                && nav.dom() === 1) { nav.push(2); }
        }, true);

        // A right swipe that starts on a history line must not open the sidebar.
        var touch = null;
        document.addEventListener("touchstart", function (e) {
            touch = null;
            if (!e.touches || e.touches.length !== 1) { return; }
            if (e.target.closest && e.target.closest(".ud-entry")) { touch = { x: e.touches[0].clientX }; }
        }, { passive: true, capture: true });
        document.addEventListener("touchend", function (e) {
            var s = touch;
            touch = null;
            if (s && e.changedTouches && e.changedTouches.length && e.changedTouches[0].clientX - s.x >= 40) {
                e.stopPropagation();
            }
        }, { passive: false, capture: true });

        // Number keypad for the mobile / amount boxes, and the amount box is
        // ready to type in as soon as it appears.
        function fixInputs() {
            var inputs = document.querySelectorAll("input");
            for (var i = 0; i < inputs.length; i++) {
                var el = inputs[i];
                var label = el.getAttribute("aria-label") || "";
                var mode = /^Mobile number/.test(label) ? "numeric" : (/^Amount/.test(label) ? "decimal" : "");
                if (!mode) { continue; }
                if (el.getAttribute("inputmode") !== mode) {
                    el.setAttribute("inputmode", mode);
                    el.setAttribute("autocomplete", "off");
                    if (mode === "numeric") { el.setAttribute("pattern", "[0-9]*"); }
                }
                if (mode === "decimal" && !el.dataset.udFocused) {
                    el.dataset.udFocused = "1";
                    try { el.focus({ preventScroll: true }); } catch (err) { /* best effort */ }
                }
            }
        }
        var queued = false;
        new MutationObserver(function () {
            if (queued) { return; }
            queued = true;
            window.requestAnimationFrame(function () { queued = false; fixInputs(); });
        }).observe(document.body, { childList: true, subtree: true });
        fixInputs();
    };
    var bridge = window.parent.document.createElement("script");
    bridge.textContent = "(" + run.toString() + ")();";
    window.parent.document.body.appendChild(bridge);
} catch (e) { /* best effort - everything still works with plain taps */ }
</script>
"""

# The phone's Back button, one step at a time. The page tells this script on
# which level it is (0 list, 1 customer, 2 entry form open); a deeper level
# adds one browser-history entry, and Back to such an entry presses the hidden
# "udhar_nav_back" button, which goes one step up.
_NAV_JS = """
<script>
(function () {
    try {
        var host = window.parent;
        if (!host.__easystockUdharNav) {
            var install = function () {
                var PAGE = "\\ud83d\\udcd2 Udhar Khata";
                var nav = window.__easystockUdharNav = { level: 0, skip: false, fromPop: false };
                // what is really on the screen: 0 list, 1 customer, 2 entry form
                nav.dom = function () {
                    if (!document.querySelector(".st-key-udhar_nav_back")) { return 0; }
                    return document.querySelector(".st-key-udhar_entry_box_gave, .st-key-udhar_entry_box_got") ? 2 : 1;
                };
                // called at the moment of the tap (a real user action), before the page answers
                nav.push = function (level) {
                    try {
                        if (level > nav.level) {
                            history.pushState({ es_page: PAGE, es_udhar: level }, "");
                            nav.level = level;
                        }
                    } catch (err) { /* no history support */ }
                };
                nav.sync = function (level, fresh) {
                    try {
                        var state = history.state;
                        if (fresh) {
                            nav.level = 0;
                            if (state && typeof state === "object" && state.es_udhar) {
                                history.replaceState(Object.assign({}, state, { es_udhar: 0 }), "");
                            }
                        }
                        if (level > nav.level) {
                            history.pushState({ es_page: PAGE, es_udhar: level }, "");
                        } else if (level < nav.level && !nav.fromPop) {
                            nav.skip = true;                       // the app itself went back: drop the extra entry
                            history.go(level - nav.level);
                            setTimeout(function () { nav.skip = false; }, 800);
                        }
                    } catch (err) { /* no history support: Back simply leaves the page */ }
                    nav.fromPop = false;
                    nav.level = level;
                };
                window.addEventListener("popstate", function (e) {
                    if (nav.skip) { nav.skip = false; return; }
                    var s = e.state;
                    if (!s || s.es_page !== PAGE) { return; }
                    if (!document.querySelector(".ud-page")) { return; }      // another page is showing: the app's own Back handles it
                    var shown = nav.dom();
                    if (shown > 0) {
                        // something deeper is on the screen: Back goes exactly one step up
                        nav.fromPop = true;
                        nav.level = shown - 1;
                        var button = document.querySelector(".st-key-udhar_nav_back button");
                        if (button) { button.click(); }
                    } else {
                        // the list is already showing: this is an old, left-over entry - skip it
                        nav.level = 0;
                        history.back();
                    }
                });
            };
            var bridge = host.document.createElement("script");
            bridge.textContent = "(" + install.toString() + ")();";
            host.document.body.appendChild(bridge);
        }
        if (host.__easystockUdharNav) { host.__easystockUdharNav.sync(__LEVEL__, __FRESH__); }
    } catch (e) { /* best effort */ }
})();
</script>
"""


def render_udhar_page() -> None:
    st.subheader("📒 Udhar Khata")
    try:
        if _STATE not in st.session_state:
            st.session_state[_FRESH] = True          # opened just now: Back-button levels start again
        store_id = get_current_store_id()
        st.markdown(_CSS, unsafe_allow_html=True)
        components.html(_BEHAVIOUR_JS, height=0)
        selected = st.session_state.get(_SELECTED)
        if selected is not None and _find_customer(store_id, selected) is not None:
            _render_customer(store_id, selected)
        else:
            st.session_state.pop(_SELECTED, None)
            _render_list(store_id)
    except Exception as error:
        st.error(_TABLE_HELP + str(error))


def _sync_nav(level: int) -> None:
    fresh = bool(st.session_state.pop(_FRESH, False))
    components.html(
        _NAV_JS.replace("__LEVEL__", str(int(level))).replace("__FRESH__", "true" if fresh else "false"),
        height=0,
    )


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
    st.session_state.pop(_HLIMIT, None)


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


def _tiles_html(totals: dict) -> str:
    color = _RED if totals["total"] > 0 else _GREEN
    return (
        "<div class='ud-tiles'>"
        "<div class='ud-tile'><div class='ud-tl'>Kul lena hai</div>"
        f"<div class='ud-tv' style='color:{color};'>{html.escape(service.money(totals['total']))}</div></div>"
        "<div class='ud-tile'><div class='ud-tl'>Kitno ka baaki</div>"
        f"<div class='ud-tv'>{totals['count']}</div></div>"
        "</div>"
    )


def _initial(name: str) -> str:
    for ch in str(name):
        if ch.isalnum():
            return ch.upper()
    return "?"


def _avatar_color(name: str) -> str:
    return _AVATAR_COLORS[sum(ord(ch) for ch in str(name)) % len(_AVATAR_COLORS)]


def _row_html(row: dict) -> str:
    balance = row["balance"]
    if balance > 0:
        amount = f"<b style='color:{_RED};'>{html.escape(service.money(balance))}</b><small>Lena hai</small>"
    elif balance < 0:
        amount = f"<b style='color:{_GREEN};'>{html.escape(service.money(balance))}</b><small>Advance</small>"
    else:
        amount = "<small>Barabar ✅</small>"
    name = str(row["name"])
    return (
        f"<div class='ud-row ud-id-{int(row['customer_id'])}'>"
        f"<div class='ud-av' style='background:{_avatar_color(name)};'>{html.escape(_initial(name))}</div>"
        f"<div class='ud-name'>{html.escape(name)}</div>"
        f"<div class='ud-amt'>{amount}</div></div>"
    )


def _more_customers() -> None:
    st.session_state[_LIMIT] = st.session_state.get(_LIMIT, PAGE_SIZE) + PAGE_SIZE


@st.fragment
def _render_list(store_id: int) -> None:
    """A fragment: typing in the search box redraws only this list."""
    _sync_nav(0)
    customers = _state(store_id)["customers"]
    _show_flash()

    st.markdown(_tiles_html(service.summary(customers)), unsafe_allow_html=True)
    if customers:
        store_name = get_current_store_name()          # read here: the PDF is made in another thread
        pdf_export.pdf_button(
            "Download record", lambda: service.build_pdf(store_id, store_name), "Udhar_Khata", "udhar",
        )

    _render_add_customer(store_id)

    if not customers:
        st.info("Abhi koi customer nahi hai. Upar ➕ se pehla customer jodo.")
        return

    term = _search_box().strip().lower()
    if st.session_state.get(_LAST_TERM) != term:          # a new search starts from the top
        st.session_state[_LAST_TERM] = term
        st.session_state[_LIMIT] = PAGE_SIZE
    digits = "".join(ch for ch in term if ch.isdigit())
    shown = [
        row for row in customers
        if not term or term in row["name"].lower() or (digits and digits in row["mobile"])
    ]
    if not shown:
        st.info("Koi customer nahi mila.")
        return

    limit = st.session_state.get(_LIMIT, PAGE_SIZE)
    page = shown[:limit]
    st.markdown("<div class='ud-list'>" + "".join(_row_html(row) for row in page) + "</div>", unsafe_allow_html=True)
    # Hidden by CSS: tapping a row presses its button (the page opens the customer).
    for row in page:
        if st.button("open", key=f"udhar_open_{row['customer_id']}"):
            _open_customer(row["customer_id"])
            st.rerun()                       # the whole page: the customer screen replaces the list
    if len(shown) > len(page):
        st.button(
            f"⬇️ Aur {min(PAGE_SIZE, len(shown) - len(page))} dikhao", key="udhar_more",
            use_container_width=True, on_click=_more_customers,
        )


def _bump(key: str) -> None:
    st.session_state[key] = st.session_state.get(key, 0) + 1


def _render_add_customer(store_id: int) -> None:
    name_key = f"udhar_nc_name_{st.session_state.get(_NC_NAME_V, 0)}"
    mobile_key = f"udhar_nc_mobile_{st.session_state.get(_NC_MOBILE_V, 0)}"
    with st.expander("➕ Naya customer", expanded=bool(st.session_state.get(_NC_OPEN))):
        with st.container(key="udhar_form_box"):
            with st.form("udhar_new_customer", clear_on_submit=False, border=False):
                name = st.text_input("Naam", placeholder="Customer ka naam", key=name_key)
                mobile = st.text_input("Mobile number", placeholder="10 ank ka number", key=mobile_key)
                submitted = st.form_submit_button("Save", type="primary", use_container_width=True)
        if not submitted:
            return
        result = service.add_customer(store_id, name, mobile)
        status = result["status"]
        if status == "added":
            _refresh(store_id)
            _bump(_NC_NAME_V)
            _bump(_NC_MOBILE_V)
            st.session_state.pop(_NC_OPEN, None)
            _open_customer(result["customer_id"])
            st.rerun()
        # A mistake empties only the box that is wrong; the other one stays.
        st.session_state[_NC_OPEN] = True
        if status == "exists":
            st.session_state[_FLASH] = ("warning", f"Ye number pehle se hai: {result.get('name', '')}.")
            _bump(_NC_MOBILE_V)
        elif status == "bad_name":
            st.session_state[_FLASH] = ("warning", "Naam 2 se 60 akshar ka likho.")
            _bump(_NC_NAME_V)
        else:
            st.session_state[_FLASH] = ("warning", "Sahi 10 ank ka mobile number likho.")
            _bump(_NC_MOBILE_V)
        st.rerun(scope="fragment")


# -------------------------------------------------------- customer view

def _back() -> None:
    st.session_state.pop(_SELECTED, None)
    st.session_state.pop(_MODE, None)
    st.session_state.pop(_CONFIRM, None)
    st.session_state.pop(_HLIMIT, None)


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


def _more_history() -> None:
    st.session_state[_HLIMIT] = st.session_state.get(_HLIMIT, HISTORY_PAGE_SIZE) + HISTORY_PAGE_SIZE


@st.fragment
def _render_customer(store_id: int, customer_id: int) -> None:
    """A fragment: entries, delete and the forms redraw only this screen."""
    customer = _find_customer(store_id, customer_id)
    if customer is None:
        return
    mode = st.session_state.get(_MODE)
    mode = mode if mode in (service.KIND_GAVE, service.KIND_GOT) else None
    _sync_nav(2 if mode else 1)

    # Hidden: the phone's Back button presses it (one step up).
    if st.button("back", key="udhar_nav_back"):
        if mode:
            st.session_state[_MODE] = None
            st.rerun(scope="fragment")
        _back()
        st.rerun()

    if st.button("← Sab customers", key="udhar_back", on_click=_back):
        st.rerun()                           # back to the list: the whole page

    _show_flash()
    balance = customer["balance"]
    color = _RED if balance > 0 else _GREEN
    st.markdown(
        "<div style='text-align:center; margin:0.2rem 0 0.5rem 0;'>"
        f"<div style='font-size:1.3rem; font-weight:700;'>{html.escape(customer['name'])}</div>"
        f"<div style='font-size:0.85rem; color:#888;'>📱 {html.escape(customer['mobile'])}</div>"
        f"<div style='font-size:1.8rem; font-weight:800; color:{color};'>{html.escape(_balance_text(balance))}</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    with st.container(key="udhar_actions"):
        gave_col, got_col = st.columns(2)
        with gave_col:
            st.button("Udhar diya", key="udhar_mode_gave", use_container_width=True,
                      on_click=_set_mode, args=(service.KIND_GAVE,))
        with got_col:
            st.button("Paise mile", key="udhar_mode_got", use_container_width=True,
                      on_click=_set_mode, args=(service.KIND_GOT,))
    if mode:
        _render_entry_form(store_id, customer, mode)

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
    _render_history(store_id, history)
    if balance > 0 and not mode:
        _render_reminder_bar(customer)


def _render_reminder_bar(customer: dict) -> None:
    """Fixed at the bottom (only the list scrolls): WhatsApp and SMS reminder."""
    message = service.reminder_message(get_current_store_name(), customer["name"], customer["balance"])
    st.markdown("<div style='height:8.5rem;'></div>", unsafe_allow_html=True)      # the last line is not hidden behind the bar
    with st.container(key="udhar_bar"):
        wa_col, sms_col = st.columns(2)
        with wa_col:
            with st.container(key="udhar_wa"):
                st.link_button("💬 WhatsApp reminder", service.whatsapp_url(customer["mobile"], message),
                               use_container_width=True)
        with sms_col:
            with st.container(key="udhar_sms"):
                st.link_button("✉️ SMS reminder", service.sms_url(customer["mobile"], message),
                               use_container_width=True)


def _render_entry_form(store_id: int, customer: dict, mode: str) -> None:
    with st.container(key=f"udhar_entry_box_{mode}"):
        with st.form(f"udhar_entry_form_{mode}", clear_on_submit=False, border=False):
            amount = st.text_input("Amount ₹", placeholder="Kitne rupaye", key=f"udhar_amount_{mode}")
            note = st.text_input("Note (zaroori nahi)", placeholder="jaise: Dolo 2 strip", key=f"udhar_note_{mode}")
            when = st.date_input("Tareekh", value=service.today_ist(), format="DD/MM/YYYY", key=f"udhar_date_{mode}")
            with st.container(key=f"udhar_save_{mode}"):
                label = "Udhar diya - Save" if mode == service.KIND_GAVE else "Paise mile - Save"
                submitted = st.form_submit_button(label, use_container_width=True)
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


def _entry_html(entry: dict, asking: bool) -> str:
    gave = entry["kind"] == service.KIND_GAVE
    color = _RED if gave else _GREEN
    sign = "−" if gave else "+"
    title = "Udhar diya" if gave else "Paise mile"
    try:
        day = date.fromisoformat(str(entry["entry_date"])[:10]).strftime("%d %b %Y")
    except ValueError:
        day = str(entry["entry_date"])
    detail = title + (f" • {entry['note']}" if entry.get("note") else "")
    ask = (
        "<div class='ud-ask'><span class='ud-q'>Pakka hatani hai?</span>"
        "<span class='ud-no'>Nahi</span><span class='ud-yes'>Haan, hatao</span></div>"
        if asking else ""
    )
    return (
        f"<div class='ud-entry ud-id-{int(entry['entry_id'])}'>"
        "<div class='ud-main'>"
        f"<div><div class='ud-d'>{html.escape(day)}</div><div class='ud-n'>{html.escape(detail)}</div></div>"
        f"<div class='ud-r'><div class='ud-a' style='color:{color};'>{sign}{html.escape(service.money(entry['amount']))}</div>"
        f"<div class='ud-b'>Baaki {html.escape(service.money(entry['balance_after']))}"
        f"{' (advance)' if entry['balance_after'] < 0 else ''}</div></div>"
        f"</div>{ask}</div>"
    )


def _render_history(store_id: int, history: list) -> None:
    limit = st.session_state.get(_HLIMIT, HISTORY_PAGE_SIZE)
    page = history[:limit]
    asking = st.session_state.get(_CONFIRM)
    st.caption(f"{len(history)} entry  •  hatane ke liye entry ko right slide karo")
    st.markdown(
        "<div class='ud-list'>" + "".join(_entry_html(entry, entry["entry_id"] == asking) for entry in page) + "</div>",
        unsafe_allow_html=True,
    )
    # Hidden by CSS: the gestures press these (the real work is the Python callbacks).
    for entry in page:
        st.button("delete?", key=f"udhar_del_{entry['entry_id']}", on_click=_ask_delete, args=(entry["entry_id"],))
        if entry["entry_id"] == asking:
            st.button("yes", key=f"udhar_yes_{entry['entry_id']}", on_click=_do_delete, args=(store_id, entry["entry_id"]))
            st.button("no", key=f"udhar_no_{entry['entry_id']}", on_click=_cancel_delete)
    if len(history) > len(page):
        st.button(
            f"⬇️ Aur {min(HISTORY_PAGE_SIZE, len(history) - len(page))} dikhao", key="udhar_history_more",
            use_container_width=True, on_click=_more_history,
        )