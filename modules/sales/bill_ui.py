"""Bill mode of the Sales screen.

A switch at the top of Sales ("🧾 Bill mode") turns it on. With it OFF the
Sales screen is exactly what it always was; this file is only used when it
is ON.

In Bill mode the owner:
  1. types a medicine name - suggestions appear as they type (needs the
     streamlit-keyup package; without it a normal box is used and Enter /
     the Search button show the suggestions, as before);
  2. taps a suggestion - it is added to the bill below;
  3. sets each medicine's quantity with the same - / + blocks as Quick Setup
     (and Strip | Tablet where the pack is known);
  4. sees the total (MRP x quantity) at the bottom and sells everything with
     ONE button.

A medicine that is not in the store's stock (taken from the medicine list,
or typed in full) is added with MRP 0: an "MRP" button next to the Strip /
Tablet choice opens a box where the owner sets the MRP (with - / + or by
typing). When the bill is sold, such a medicine is put into the system
(with 0 stock left) and the sale is recorded - see bill_service.

All calculations and selling live in modules/sales/bill_service.py.
"""

import copy
import html
import time

import streamlit as st
import streamlit.components.v1 as components

from core.cache_utils import bump_cache_epoch, get_cache_epoch
from core.session import get_current_store_name
from modules.billing import service as billing_service
from modules.sales import bill_service
from modules.sales import service as sales_service

try:
    from st_keyup import st_keyup
except ImportError:          # package not installed: a normal text box is used instead
    st_keyup = None

_LINES = "sales_bill_lines"
_NEXT_ID = "sales_bill_next_id"
_SEARCH_VERSION = "sales_bill_search_version"
_FLASH = "sales_bill_flash"
_UNIT_CHOICE = "sales_bill_unit_choice"
_STORE_OWNER = "sales_bill_store"
_KEYUP_DEBOUNCE_MS = 150
_CATALOG_KEY = "bill_store_catalog"
_CATALOG_MAX_AGE_SECONDS = 120
_PRINT = "sales_bill_print_payload"
_FORM_OPEN = "sales_bill_form_open"
_LAST_BILL = "sales_bill_last"
# Tablets per strip that are common in India (most are 10, 14 or 15). Kept to
# 9 on purpose: Streamlit does not pop up the phone keyboard for a short list.
_COMMON_PACKS = (4, 6, 8, 10, 12, 14, 15, 20, 30)
_DETAIL_KEYS = ("bill_customer_name", "bill_customer_mobile", "bill_customer_doctor", "bill_customer_address")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def render_bill_mode(store_id: int) -> bool:
    """Draw the Bill mode switch. If it is ON, draw the whole bill screen and
    return True (the caller then skips the normal one-medicine screen);
    if it is OFF return False and draw nothing else."""
    # Streamlit forgets a switch while another page is open, so the choice is
    # also kept under a plain key and put back when the owner returns.
    if "sales_bill_mode" not in st.session_state:
        st.session_state["sales_bill_mode"] = st.session_state.get("sales_bill_mode_memory", True)
    is_on = st.toggle("🧾 Bill mode - ek saath kai dawaiyan bechna", key="sales_bill_mode")
    st.session_state["sales_bill_mode_memory"] = is_on
    if not is_on:
        return False

    _reset_if_other_store(store_id)
    _inject_css()
    _inject_swipe_script()
    lines = st.session_state.setdefault(_LINES, [])
    _show_flash()
    _show_print()
    _render_search(store_id)
    _render_bill_body(store_id)
    return True


@st.fragment
def _render_bill_body(store_id: int) -> None:
    """The medicine blocks, the total and the buttons. A fragment: pressing a
    button here (Tablet, MRP, - / +, swipe, Bill ...) redraws ONLY this part -
    not the search box, the Frequently Sold list or the rest of the page - so
    the answer comes back much faster. (Anything that must redraw the whole
    page, like Print or Sell all, calls st.rerun() itself.)"""
    lines = st.session_state.setdefault(_LINES, [])
    _render_bill_lines(lines)
    _render_total_and_sell(store_id, lines)


def _reset_if_other_store(store_id: int) -> None:
    """Logout only removes the login, so a different store signing in on the
    same browser session must never see the previous store's bill."""
    previous = st.session_state.get(_STORE_OWNER)
    if previous is not None and previous != store_id:
        for key in [
            key for key in st.session_state
            if str(key).startswith(("sales_bill_", "bill_")) and key != _STORE_OWNER
        ]:
            del st.session_state[key]
    st.session_state[_STORE_OWNER] = store_id


def _inject_css() -> None:
    """Same look as the Quick Setup medicine blocks: square - / + on both
    sides of the name, never stacked on a phone. Scoped to the containers
    keyed bill_row_ and bill_ctl_ only."""
    st.markdown(
        """
        <style>
        div[class*="st-key-bill_row_"] div[data-testid="stHorizontalBlock"],
        div[class*="st-key-bill_ctl_"] div[data-testid="stHorizontalBlock"] {
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            gap: 0.4rem !important;
            align-items: center !important;
        }
        div[class*="st-key-bill_row_"] div[data-testid="stColumn"],
        div[class*="st-key-bill_ctl_"] div[data-testid="stColumn"] {
            width: auto !important;
            min-width: 0 !important;
        }
        div[class*="st-key-bill_row_"] div[data-testid="stColumn"]:first-child,
        div[class*="st-key-bill_row_"] div[data-testid="stColumn"]:last-child {
            flex: 0 0 56px !important;
        }
        div[class*="st-key-bill_row_"] div[data-testid="stColumn"]:not(:first-child):not(:last-child) {
            flex: 1 1 auto !important;
        }
        div[class*="st-key-bill_ctl_"] div[data-testid="stColumn"]:nth-child(1) { flex: 3 1 0 !important; }
        div[class*="st-key-bill_ctl_"] div[data-testid="stColumn"]:nth-child(2) { flex: 1.4 1 0 !important; }
        div[class*="st-key-bill_ctl_"] div[data-testid="stColumn"]:nth-child(3) { flex: 1 1 0 !important; }
        div[class*="st-key-bill_row_"] button[kind="secondary"] {
            aspect-ratio: 1 / 1;
            font-size: 1.4rem;
        }
        div[class*="st-key-bill_utog_"] div[data-testid="stHorizontalBlock"],
        div[class*="st-key-bill_actions"] div[data-testid="stHorizontalBlock"] {
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            gap: 0.4rem !important;
            align-items: center !important;
        }
        div[class*="st-key-bill_utog_"] div[data-testid="stColumn"],
        div[class*="st-key-bill_actions"] div[data-testid="stColumn"] {
            width: auto !important;
            min-width: 0 !important;
        }
        div[class*="st-key-bill_utog_"] div[data-testid="stColumn"]:first-child,
        div[class*="st-key-bill_utog_"] div[data-testid="stColumn"]:last-child {
            flex: 0 0 56px !important;
        }
        div[class*="st-key-bill_utog_"] div[data-testid="stColumn"]:not(:first-child):not(:last-child) {
            flex: 1 1 auto !important;
        }
        div[class*="st-key-bill_actions"] div[data-testid="stColumn"] {
            flex: 1 1 0 !important;
        }
        div[class*="st-key-bill_utog_"] button {
            min-height: 1.9rem !important;
            padding: 0.1rem 0.2rem !important;
            font-size: 0.72rem !important;
        }
        div[class*="st-key-bill_card_"] [data-testid="stVerticalBlock"] {
            gap: 0.35rem !important;
        }
        div[class*="st-key-bill_card_"] {
            touch-action: pan-y;
        }
        div[class*="st-key-bill_remove_"] {
            display: none !important;
        }
        div[class*="st-key-bill_"] button {
            touch-action: manipulation;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _inject_swipe_script() -> None:
    """Swipe a medicine block to the RIGHT (finger on a phone, mouse drag on a
    PC) to remove it. The block FOLLOWS the finger and fades while it moves;
    let go past a third of the width (or with a quick flick) and it flies off
    to the right, otherwise it springs back.

    Streamlit has no swipe gesture, so this small script only DRAGS the block
    and presses that block's own hidden remove button - the removal itself is
    the normal Python callback _remove_line, started the moment the block
    leaves. It fails silently if the page structure is not found, and
    installs itself once per browser tab."""
    components.html(
        """
        <script>
        try {
            var run = function () {
                if (window.__easystockBillSwipeV2) { return; }
                window.__easystockBillSwipeV2 = true;
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
                    if (e.target.closest("button, input, textarea, label, a, [role='radiogroup']")) { return; }
                    var card = e.target.closest('[class*="st-key-bill_card_"]');
                    if (!card) { return; }
                    var idPart = String(card.className).split("st-key-bill_card_")[1];
                    var lineId = idPart ? parseInt(idPart, 10) : NaN;
                    if (isNaN(lineId)) { return; }
                    drag = {
                        id: lineId, box: boxOf(card), x: e.clientX, y: e.clientY,
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
                            drag.main.style.overflowX = "hidden";            // no sideways scrollbar while the block slides out
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
                    var button = document.querySelector(".st-key-bill_remove_" + d.id + " button");
                    if (button) { button.click(); }                              // the real removal starts at once
                    // When the block is really gone from the page (or after 3 s, if
                    // not), clear the styles: the page may reuse this same box for
                    // the next medicine, which must not stay hidden.
                    var tries = 0;
                    var timer = setInterval(function () {
                        tries += 1;
                        var stillThere = document.querySelector(".st-key-bill_remove_" + d.id + " button");
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
        } catch (e) { /* best effort - the bill works without swipe */ }
        </script>
        """,
        height=0,
    )

# ---------------------------------------------------------------------------
# Search and suggestions
# ---------------------------------------------------------------------------

def _search_box() -> str:
    """The search box. With streamlit-keyup the text is sent after every short
    pause in typing; without it, Enter (or tapping elsewhere / the Search
    button) sends it. A new key (version) gives an empty box after a medicine
    has been added."""
    key = f"bill_search_{st.session_state.get(_SEARCH_VERSION, 0)}"
    hint = "Dawai ka naam likho (jaise Dolo)"
    if st_keyup is not None:
        try:
            text = st_keyup(
                "Search medicine", placeholder=hint, debounce=_KEYUP_DEBOUNCE_MS,
                key=key, label_visibility="collapsed",
            )
        except TypeError:            # an older version without placeholder / label options
            text = st_keyup("Search medicine", debounce=_KEYUP_DEBOUNCE_MS, key=key)
        return text or ""
    text = st.text_input("Search medicine", placeholder=hint, key=key, label_visibility="collapsed")
    st.button("🔎 Search", key="bill_search_button", use_container_width=True)
    return text or ""


def _store_catalog(store_id: int) -> list:
    """ALL of this store's product rows, read from the database ONCE and kept
    in the session; every keystroke is then answered from memory. It is read
    again after any stock change, for another store, or when 2 minutes old."""
    epoch = get_cache_epoch(store_id)
    saved = st.session_state.get(_CATALOG_KEY)
    if (
        saved is not None and saved["store_id"] == store_id and saved["epoch"] == epoch
        and time.monotonic() - saved["at"] < _CATALOG_MAX_AGE_SECONDS
    ):
        return saved["rows"]
    rows = sales_service.get_store_catalog(store_id)
    st.session_state[_CATALOG_KEY] = {"store_id": store_id, "epoch": epoch, "rows": rows, "at": time.monotonic()}
    return rows


@st.cache_data(show_spinner=False, ttl=300)
def _outside_stock_cached(term: str) -> dict:
    """The term is not in the store's stock: offer the medicine list; only if
    that has none either, an "add what you typed" choice."""
    master = sales_service.search_master_medicines(term)
    if master:
        return {"kind": "master", "items": master}
    is_valid, name = sales_service.is_valid_new_medicine_name(term)
    if is_valid:
        return {"kind": "new", "items": [], "name": name}
    return {"kind": "none", "items": []}


def _suggestions(store_id: int, term: str) -> dict:
    """The store's own stock first (from memory); only if there is none, the
    medicine list; only if that has none either, "add what you typed"."""
    catalog = _store_catalog(store_id)
    stock = sales_service.search_store_products(store_id, term, catalog)
    zero = bill_service.zero_stock_matches(catalog, term)       # in the system, but 0 stock
    if stock or zero:
        return {"kind": "stock", "items": stock, "zero_items": zero}
    return _outside_stock_cached(term)

def _tile(label: str, key: str, action, *args) -> None:
    """A medicine tile of the search list. The search part of the page is its
    own fragment (typing redraws only it); a tap changes the BILL below, so it
    runs the action and redraws the whole page once."""
    if st.button(label, key=key, use_container_width=True):
        action(*args)
        st.rerun()


@st.fragment
def _render_search(store_id: int) -> None:
    """The search box and what it offers. A fragment: every keystroke redraws
    only this part, not the bill (medicine blocks, total, buttons) below it."""
    term = _search_box().strip()
    _store_catalog(store_id)          # read once, so typing below is instant
    if not term:
        _render_frequently_sold_in_bill(store_id)
        return
    result = _suggestions(store_id, term)

    if result["kind"] == "stock":
        for index, product in enumerate(result["items"]):
            mrp = bill_service.to_number(product.get("mrp"))
            _tile(
                f"**{product['name']}**\nMRP {_money(mrp)} • Stock: {_stock_text(product['quantity'])}",
                f"bill_add_stock_{index}", _add_stock_line, store_id, product,
            )
        for index, product in enumerate(result.get("zero_items", [])):
            mrp = bill_service.to_number(product.get("mrp"))
            _tile(
                f"**{product['name']}**\nMRP {_money(mrp)} • ⚠️ Stock: 0",
                f"bill_add_zero_{index}", _add_zero_line, product,
            )
    elif result["kind"] == "master":
        for index, medicine in enumerate(result["items"]):
            detail = medicine.get("composition") or ""
            label = f"**{medicine['name']}**\n{detail}" if detail else f"**{medicine['name']}**"
            _tile(label, f"bill_add_master_{index}", _add_unlisted_line, "master", medicine["name"])
    elif result["kind"] == "new":
        _tile(
            f"➕ Add \"{result['name']}\" as a new medicine", "bill_add_new",
            _add_unlisted_line, "new", result["name"],
        )
    else:
        st.info("No products match your search.")

@st.cache_data(show_spinner=False, ttl=300)
def _bill_frequently_sold_cached(store_id: int, _epoch: int, _catalog: list) -> list:
    # The store's rows are already loaded (_store_catalog): no second full read.
    return sales_service.get_frequently_sold(store_id, _catalog)


def _render_frequently_sold_in_bill(store_id: int) -> None:
    """Frequently Sold tiles in Bill mode - tapping adds to the bill."""
    products = _bill_frequently_sold_cached(store_id, get_cache_epoch(store_id), _store_catalog(store_id))
    if not products:
        return
    st.caption("⭐ Frequently Sold")
    for index, product in enumerate(products):
        _tile(
            f"**{product['name']}**  •  Stock: {_stock_text(product['quantity'])}",
            f"bill_freq_{index}", _add_stock_line, store_id, product,
        )

def _stock_text(quantity) -> str:
    """Stock of the first batch for a suggestion. A whole number as it is;
    a part strip (loose tablets) as "8+ strips" - never a decimal."""
    quantity = bill_service.to_number(quantity)
    if abs(quantity - round(quantity)) < 1e-9:
        return str(int(round(quantity)))
    return f"{int(quantity)}+ strips"


def _money(amount: float) -> str:
    """₹1,234.5 - two decimals only where they are needed."""
    text = f"{amount:,.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"₹{text}"


# ---------------------------------------------------------------------------
# Changing the bill (these run as button callbacks, before the page redraws)
# ---------------------------------------------------------------------------

def _new_line_id() -> int:
    line_id = st.session_state.get(_NEXT_ID, 1)
    st.session_state[_NEXT_ID] = line_id + 1
    return line_id


def _clear_search() -> None:
    st.session_state[_SEARCH_VERSION] = st.session_state.get(_SEARCH_VERSION, 0) + 1


def _find_line(line_id: int):
    return next((line for line in st.session_state.get(_LINES, []) if line["id"] == line_id), None)

def _drop_sold_lines() -> None:
    """A medicine added after a bill was sold is a new customer: the sold
    blocks leave the screen (the Re-generate copy of that bill stays)."""
    lines = st.session_state.get(_LINES, [])
    for line in lines:
        if line.get("sold"):
            _drop_widget_keys(line["id"])
    st.session_state[_LINES] = [line for line in lines if not line.get("sold")]

def _add_stock_line(store_id: int, product: dict) -> None:
    _drop_sold_lines()
    lines = st.session_state.setdefault(_LINES, [])
    existing = next((line for line in lines if bill_service.same_medicine(line, "stock", product["name"])), None)
    if existing is not None:
        _change_quantity(existing["id"], 1)
    else:
        unit = st.session_state.get(_UNIT_CHOICE, "Strip")
        line = bill_service.build_stock_line(store_id, _new_line_id(), product, unit)
        lines.append(line)
        # From now this line keeps its OWN unit - a button on another line never changes it.
        st.session_state[f"bill_unit_{line['id']}"] = unit if line.get("pack_from_db") else "Strip"
    
    # Version bump separately so the search clears without blocking the add
    st.session_state[_SEARCH_VERSION] = st.session_state.get(_SEARCH_VERSION, 0) + 1

def _add_zero_line(product: dict) -> None:
    """A medicine the system has with 0 stock: added like a new medicine (no
    stock limit), with its MRP and pack from the system."""
    _drop_sold_lines()
    lines = st.session_state.setdefault(_LINES, [])
    existing = next((line for line in lines if bill_service.same_medicine(line, "zero", product["name"])), None)
    if existing is not None:
        _change_quantity(existing["id"], 1)
    else:
        unit = st.session_state.get(_UNIT_CHOICE, "Strip")
        line = bill_service.build_zero_line(_new_line_id(), product, unit)
        lines.append(line)
        st.session_state[f"bill_unit_{line['id']}"] = unit if line.get("pack_from_db") else "Strip"
    st.session_state[_SEARCH_VERSION] = st.session_state.get(_SEARCH_VERSION, 0) + 1

def _add_unlisted_line(kind: str, name: str) -> None:
    _drop_sold_lines()
    lines = st.session_state.setdefault(_LINES, [])
    existing = next((line for line in lines if bill_service.same_medicine(line, kind, name)), None)
    if existing is not None:
        _change_quantity(existing["id"], 1)
    else:
        lines.append(bill_service.build_unlisted_line(_new_line_id(), kind, name))
    st.session_state[_SEARCH_VERSION] = st.session_state.get(_SEARCH_VERSION, 0) + 1


def _set_unit(line_id: int, unit: str) -> None:
    """Strip / Tablet button: what - and + add from now on."""
    st.session_state[f"bill_unit_{line_id}"] = unit
    st.session_state[_UNIT_CHOICE] = unit


def _unit_of(line: dict) -> str:
    own = st.session_state.get(f"bill_unit_{line['id']}")
    if own:
        return own
    return "Strip"


def _step(line: dict) -> int:
    """How much - and + change the quantity: one strip (its tablets) or one
    tablet when the pack is known and Tablet is chosen; else 1."""
    if not line.get("pack"):
        return 1
    return 1 if _unit_of(line) == "Tablet" else line["pack"]


def _commit_pack(line: dict) -> None:
    """Take the pack size typed in the open pack box (it is read from the box
    itself, so it is kept even if the box is being closed right now)."""
    value = st.session_state.get(f"bill_pack_{line['id']}")
    if value and int(value) >= 2 and int(value) != line.get("pack"):
        bill_service.apply_pack(line, int(value))


def _close_pack_box(line: dict) -> None:
    """Hide the pack box. If no pack was entered, Tablet makes no sense yet:
    the medicine goes back to Strip."""
    line_id = line["id"]
    _commit_pack(line)
    st.session_state[f"bill_pack_edit_{line_id}"] = False
    if not line.get("pack") and not line.get("pack_from_db"):
        st.session_state[f"bill_unit_{line_id}"] = "Strip"

def _pick_common_pack(line_id: int) -> None:
    """A pack size was chosen from the list: use it (the typing box shows it
    too) and get the list ready for the next pick."""
    pick_key = f"bill_packpick_{line_id}"
    chosen = st.session_state.get(pick_key)
    st.session_state[pick_key] = None
    line = _find_line(line_id)
    if line is None or not chosen:
        return
    st.session_state[f"bill_pack_{line_id}"] = int(chosen)
    bill_service.apply_pack(line, int(chosen))

def _on_strip_press(line_id: int) -> None:
    line = _find_line(line_id)
    if line is not None and st.session_state.get(f"bill_pack_edit_{line_id}"):
        _commit_pack(line)
        st.session_state[f"bill_pack_edit_{line_id}"] = False
    _set_unit(line_id, "Strip")


def _on_tablet_press(line_id: int) -> None:
    """Tablet works like the MRP button. Pack known: just switch to tablets.
    Pack not known: the first press opens the pack box (the button shows a
    tick); the tick closes it again - and so does - / +."""
    line = _find_line(line_id)
    if line is None:
        return
    box_key = f"bill_pack_edit_{line_id}"
    if line.get("pack_from_db"):
        _set_unit(line_id, "Tablet")
    elif st.session_state.get(box_key):
        _close_pack_box(line)
    elif st.session_state.get(f"bill_unit_{line_id}") == "Tablet":
        st.session_state[box_key] = True                  # already tablets: open the box to change the pack
    else:
        _set_unit(line_id, "Tablet")
        st.session_state[box_key] = not line.get("pack")  # only ask while the pack is still unknown


def _change_quantity(line_id: int, direction: int) -> None:
    line = _find_line(line_id)
    if line is None:
        return
    if st.session_state.get(f"bill_pack_edit_{line_id}"):
        _close_pack_box(line)                              # - / + hides the pack box, keeping the pack typed
    new_quantity = line["qty"] + direction * _step(line)
    if line.get("stock_units") is not None:
        new_quantity = min(new_quantity, line["stock_units"])
    if new_quantity >= 1:
        line["qty"] = new_quantity

def _toggle_mrp_editor(line_id: int) -> None:
    key = f"bill_mrp_edit_{line_id}"
    st.session_state[key] = not st.session_state.get(key, False)


def _remember_unit(line_id: int) -> None:
    st.session_state[_UNIT_CHOICE] = st.session_state[f"bill_unit_{line_id}"]


def _drop_widget_keys(line_id: int) -> None:
    for key in (
        f"bill_unit_{line_id}", f"bill_mrp_edit_{line_id}", f"bill_mrp_val_{line_id}",
        f"bill_pack_{line_id}", f"bill_pack_edit_{line_id}" ,f"bill_packpick_{line_id}",
    ):
        st.session_state.pop(key, None)


def _remove_line(line_id: int) -> None:
    st.session_state[_LINES] = [line for line in st.session_state.get(_LINES, []) if line["id"] != line_id]
    _drop_widget_keys(line_id)
    if not st.session_state[_LINES]:
        st.session_state.pop(_LAST_BILL, None)


def _clear_bill() -> None:
    for line in st.session_state.get(_LINES, []):
        _drop_widget_keys(line["id"])
    st.session_state[_LINES] = []
    st.session_state.pop(_LAST_BILL, None)


# ---------------------------------------------------------------------------
# The bill
# ---------------------------------------------------------------------------

def _render_bill_lines(lines: list) -> None:
    for line in list(lines):
        _render_line(line)


def _render_unit_row(line: dict, mrp: float, editing: bool) -> None:
    """One slim row above the - / + row: Strip right above -, Tablet right
    above +, and the MRP button in the middle while the MRP is not known.
    Every medicine gets Strip / Tablet - when its pack size is not known the
    owner is asked for it (see _render_pack_input)."""
    line_id = line["id"]
    unit = _unit_of(line)
    with st.container(key=f"bill_utog_{line_id}"):
        strip_col, mrp_col, tablet_col = st.columns([1, 3, 1], vertical_alignment="center")
        with strip_col:
            st.button(
                "Strip", key=f"bill_ustrip_{line_id}", use_container_width=True,
                type="primary" if unit == "Strip" else "secondary",
                on_click=_on_strip_press, args=(line_id,),
            )
        with mrp_col:
            if mrp <= 0 or editing:
                st.button(
                    "✔" if editing else "MRP", key=f"bill_mrp_button_{line_id}",
                    use_container_width=True, on_click=_toggle_mrp_editor, args=(line_id,),
                )
        with tablet_col:
            st.button(
                "✔" if st.session_state.get(f"bill_pack_edit_{line_id}") else "Tablet",
                key=f"bill_utab_{line_id}", use_container_width=True,
                type="primary" if unit == "Tablet" else "secondary",
                on_click=_on_tablet_press, args=(line_id,),
            )


def _render_pack_input(line: dict) -> None:
    """Tablet is chosen but the system does not know the pack: ask how many
    tablets one strip holds. Until it is entered the line stays in strips;
    after that it works like any medicine with a known pack."""
    if line.get("pack_from_db") or not st.session_state.get(f"bill_pack_edit_{line['id']}"):
        return
    value = st.number_input(
        "Ek strip / pack mein kitni tablet?", min_value=2, step=1, value=line.get("pack"),
        placeholder="jaise 10", key=f"bill_pack_{line['id']}",
    )
    # A short list of the usual pack sizes: one tap instead of typing.
    st.selectbox(
        "Common pack", _COMMON_PACKS, index=None, placeholder="Ya common pack chuno",
        key=f"bill_packpick_{line['id']}", label_visibility="collapsed",
        on_change=_pick_common_pack, args=(line["id"],),
    )
    if value and int(value) != line.get("pack"):
        bill_service.apply_pack(line, int(value))

def _render_sold_line(line: dict) -> None:
    """A medicine that is already sold: same place on the screen, but only
    read - nothing on it can be pressed, so it can never be sold twice."""
    line_id = line["id"]
    mrp = bill_service.to_number(line.get("mrp"))
    amount_text = _money(bill_service.line_amount(line)) if mrp > 0 else ""
    with st.container(border=True, key=f"bill_card_{line_id}"):
        st.markdown(
            "<div style='text-align:center;'>"
            f"<div style='font-size:1.05rem; font-weight:600;'>{html.escape(line['name'])}</div>"
            "<div style='font-size:0.85rem; font-weight:700; color:#1b7a67;'>✓ Sold</div>"
            "<div style='font-size:1.3rem; font-weight:700; margin-top:2px;'>"
            f"Qty: {html.escape(bill_service.quantity_text(line))}</div>"
            f"<div style='font-size:0.8rem; color:#888;'>{html.escape(amount_text)}</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        # Hidden by CSS: the swipe gesture presses it (the sale itself stays done).
        st.button("✖", key=f"bill_remove_{line_id}", on_click=_remove_line, args=(line_id,))

def _render_line(line: dict) -> None:
    """One medicine, laid out like a Quick Setup block: square - and + on both
    sides, the name in the middle with MRP / Rate, the quantity big under it.
    Strip / Tablet sit above - and +. Swipe the block right to remove it."""
    line_id = line["id"]
    if line.get("sold"):
        _render_sold_line(line)
        return
    cap = line.get("stock_units")
    if cap is not None and cap >= 1:
        line["qty"] = max(1, min(line["qty"], cap))           # stock may have changed

    mrp = bill_service.to_number(line.get("mrp"))
    editing = st.session_state.get(f"bill_mrp_edit_{line_id}", False)

    with st.container(border=True, key=f"bill_card_{line_id}"):
        _render_unit_row(line, mrp, editing)
        _render_pack_input(line)

        step = _step(line)
        rate = line.get("rate")
        mrp_text = bill_service.line_mrp_text(line) or _money(mrp)
        subtitle = f"MRP {mrp_text} • Rate {_money(rate) if rate else '—'}"
        amount_text = _money(bill_service.line_amount(line)) if mrp > 0 else ""

        with st.container(key=f"bill_row_{line_id}"):
            minus_col, middle_col, plus_col = st.columns([1, 3, 1], vertical_alignment="center")
            with minus_col:
                st.button(
                    "➖", key=f"bill_minus_{line_id}", use_container_width=True,
                    disabled=(line["qty"] - step < 1),
                    on_click=_change_quantity, args=(line_id, -1),
                )
            with middle_col:
                st.markdown(
                    "<div style='text-align:center;'>"
                    f"<div style='font-size:1.05rem; font-weight:600;'>{html.escape(line['name'])}</div>"
                    f"<div style='font-size:0.75rem; color:#888;'>{html.escape(subtitle)}</div>"
                    "<div style='font-size:1.3rem; font-weight:700; margin-top:2px;'>"
                    f"Qty: {html.escape(bill_service.quantity_text(line))}</div>"
                    f"<div style='font-size:0.8rem; color:#888;'>{html.escape(amount_text)}</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )
            with plus_col:
                st.button(
                    "➕", key=f"bill_plus_{line_id}", use_container_width=True,
                    disabled=(cap is not None and line["qty"] >= cap),
                    on_click=_change_quantity, args=(line_id, 1),
                )

        if editing:
            value = st.number_input(
                "MRP (₹ per strip / pack)", min_value=0.0, step=1.0, format="%.2f",
                value=float(line["mrp"]), key=f"bill_mrp_val_{line_id}",
            )
            line["mrp"] = float(value)

        if line["kind"] == "master":
            st.error("⚠️ System mein nahi hai. Bechte waqt 0 stock pe add hoga.")
        elif line["kind"] == "new":
            st.error("⚠️ System mein nahi hai. Sahi naam type karo.")
        elif line["kind"] == "zero":
            st.error("⚠️ Is medicine ka stock 0 hai.")    

        # Hidden by CSS: the swipe gesture presses it (see _inject_swipe_script).
        st.button("✖", key=f"bill_remove_{line_id}", on_click=_remove_line, args=(line_id,))


# ---------------------------------------------------------------------------
# Total and Sell
# ---------------------------------------------------------------------------

def _render_total_and_sell(store_id: int, lines: list) -> None:
    if not lines:
        st.session_state[_FORM_OPEN] = False
        st.info("Bill khali hai. Upar dawai ka naam likhkar use jodo.")
        return

    pending = [line for line in lines if not line.get("sold")]      # not sold yet
    total = bill_service.bill_total(lines)
    without_mrp = sum(1 for line in pending if bill_service.to_number(line.get("mrp")) <= 0)
    count = len(lines)
    st.markdown(
        "<div style='text-align:center; margin:0.5rem 0;'>"
        f"<div style='font-size:0.85rem; color:#888;'>{count} dawai{'yan' if count != 1 else ''}</div>"
        f"<div style='font-size:2rem; font-weight:800;'>Total: {html.escape(_money(total))}</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    if without_mrp:
        st.caption(f"⚠️ {without_mrp} dawai ka MRP 0 hai - woh total mein nahi judega.")

    with st.container(key="bill_actions"):
        sell_col, bill_col = st.columns(2)
        with sell_col:
            sell_clicked = st.button(
                f"Sell all • {_money(bill_service.bill_total(pending))}", key="bill_sell_all",
                type="primary", use_container_width=True, disabled=not pending,
            )
        with bill_col:
            st.button(
                "🧾 Bill", key="bill_open_form", use_container_width=True,
                on_click=_toggle_bill_form, disabled=not pending,
            )
    if st.session_state.get(_LAST_BILL):
        with st.container(key="bill_actions_2"):
            clear_col, again_col = st.columns(2)
            with clear_col:
                st.button("🗑️ Bill khali karo", key="bill_clear", use_container_width=True, on_click=_clear_bill)
            with again_col:
                if st.button("🔁 Re-generate bill", key="bill_regenerate", use_container_width=True):
                    _regenerate_bill()
                    st.rerun()                 # whole page: the print window is drawn outside this fragment
    else:
        st.button("🗑️ Bill khali karo", key="bill_clear", use_container_width=True, on_click=_clear_bill)

    if st.session_state.get(_FORM_OPEN) and pending:
        _render_bill_form(store_id, pending)

    if sell_clicked:
        names = {line["id"]: line["name"] for line in pending}
        result = bill_service.sell_bill(store_id, pending)
        sold_ids = set(result["sold"])
        sold_total = bill_service.bill_total([line for line in pending if line["id"] in sold_ids])
        for line_id in sold_ids:
            _drop_widget_keys(line_id)
        st.session_state[_LINES] = [line for line in lines if line["id"] not in sold_ids]
        st.session_state[_FLASH] = {
            "sold_count": len(sold_ids),
            "sold_total": sold_total,
            "errors": [f"{names[line_id]}: {message}" for line_id, message in result["failed"].items()],
        }
        bump_cache_epoch(store_id)
        st.rerun()

def _toggle_bill_form() -> None:
    st.session_state[_FORM_OPEN] = not st.session_state.get(_FORM_OPEN, False)


@st.cache_data(show_spinner=False)
def _bill_settings_cached(store_id: int, _epoch: int) -> dict:
    """The store's seal / sign image and DL number (saved in Quick Setup)."""
    try:
        return billing_service.get_bill_settings(store_id)
    except Exception:
        try:                     # e.g. the DL column is not added yet: the seal must still work
            return {"seal_sign_image": billing_service.get_seal_sign(store_id), "dl_number": None}
        except Exception:
            return {"seal_sign_image": None, "dl_number": None}    # a missing setting must never stop billing


def _render_bill_form(store_id: int, lines: list) -> None:
    """The bill under the buttons: the medicines, the total, the optional
    customer details and the store's DL number / seal / sign. The easy things
    to ask come first, the harder ones last; whatever is left empty is simply
    not printed."""
    if st.session_state.pop("bill_reset_customer", False):
        for key in _DETAIL_KEYS:
            st.session_state.pop(key, None)            # a new bill starts without the old details
    st.markdown("**🧾 Bill**")
    st.caption("Ye sab optional hain - jo khaali rahega wo bill par nahi chhapega.")
    details = {
        "name": st.text_input("Customer ka naam", key="bill_customer_name"),
        "mobile": st.text_input("Mobile number", key="bill_customer_mobile", max_chars=15),
        "doctor": st.text_input("Doctor ka naam", key="bill_customer_doctor"),
        "address": st.text_input("Address", key="bill_customer_address"),
    }
    store_name = get_current_store_name()
    settings = _bill_settings_cached(store_id, get_cache_epoch(store_id))
    seal_uri = settings.get("seal_sign_image")
    dl_number = settings.get("dl_number") or ""
    st.markdown(
        billing_service.build_bill_body_html(store_name, lines, details, seal_uri, dl_number=dl_number),
        unsafe_allow_html=True,
    )
    if not seal_uri:
        st.caption("Seal / sign abhi upload nahi hui - Quick Setup mein Upload tab se upload karo.")
    if not dl_number:
        st.caption("DL number bill par tab chhapega jab Quick Setup mein save karoge.")
    if st.button("🖨️ Print", key="bill_print", type="primary", use_container_width=True):
        _sell_and_print(store_id, lines, details, seal_uri, store_name, dl_number)


def _sell_and_print(store_id: int, lines: list, details: dict, seal_uri, store_name: str, dl_number: str = "") -> None:
    """Sell the medicines that are not sold yet (same as Sell all) and print
    ONLY what was sold. The blocks STAY on the screen, marked Sold; only the
    bill form closes. A copy of the printed bill is kept, so Re-generate can
    print it again later WITHOUT selling (stock was already reduced)."""
    names = {line["id"]: line["name"] for line in lines}
    result = bill_service.sell_bill(store_id, lines)
    sold_ids = set(result["sold"])
    sold_lines = [line for line in lines if line["id"] in sold_ids]
    if sold_lines:
        st.session_state[_LAST_BILL] = {
            "store_name": store_name,
            "lines": copy.deepcopy(sold_lines),
            "customer": dict(details),
            "seal_uri": seal_uri,
            "dl_number": dl_number,
        }
        st.session_state[_PRINT] = billing_service.build_print_document(
            store_name, sold_lines, details, seal_uri, dl_number=dl_number,
        )
    for line in sold_lines:
        line["sold"] = True
    st.session_state[_FORM_OPEN] = False
    if len(sold_ids) == len(lines):
        st.session_state["bill_reset_customer"] = True
    st.session_state[_FLASH] = {
        "sold_count": len(sold_ids),
        "sold_total": bill_service.bill_total(sold_lines),
        "errors": [f"{names[line_id]}: {message}" for line_id, message in result["failed"].items()],
    }
    bump_cache_epoch(store_id)
    st.rerun()


def _regenerate_bill() -> None:
    """Print the last printed bill again. Nothing is sold here."""
    last = st.session_state.get(_LAST_BILL)
    if last:
        st.session_state[_PRINT] = billing_service.build_print_document(
            last["store_name"], last["lines"], last["customer"], last["seal_uri"],
            dl_number=last.get("dl_number", ""),
        )

def _show_print() -> None:
    """Open the print window for the bill that was just sold (once)."""
    payload = st.session_state.pop(_PRINT, None)
    if payload:
        components.html(payload, height=0)


def _show_flash() -> None:
    """The result of the last Sell. Shown on the next draw because the page is
    redrawn immediately after selling."""
    flash = st.session_state.pop(_FLASH, None)
    if not flash:
        return
    if flash["sold_count"]:
        st.success(f"✅ {flash['sold_count']} dawai bech di gayi - total {_money(flash['sold_total'])}.")
    for message in flash["errors"]:
        st.error(f"❌ {message}")