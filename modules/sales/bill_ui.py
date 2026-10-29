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

import html

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
_KEYUP_DEBOUNCE_MS = 250
_PRINT = "sales_bill_print_payload"
_FORM_OPEN = "sales_bill_form_open"


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
        st.session_state["sales_bill_mode"] = st.session_state.get("sales_bill_mode_memory", False)
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
    _render_bill_lines(lines)
    _render_total_and_sell(store_id, lines)
    return True


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
        </style>
        """,
        unsafe_allow_html=True,
    )


def _inject_swipe_script() -> None:
    """Swipe a medicine block to the RIGHT (finger on a phone, mouse drag on a
    PC) to remove it. Streamlit has no swipe gesture, so this small script only
    DETECTS the swipe and presses that block's own hidden remove button - the
    removal itself is the normal Python callback _remove_line. It fails
    silently if the page structure is not found, and installs itself once."""
    components.html(
        """
        <script>
        try {
            var run = function () {
                if (window.__easystockBillSwipe) { return; }
                window.__easystockBillSwipe = true;
                var startX = 0, startY = 0, card = null;
                document.addEventListener("pointerdown", function (e) {
                    if (e.target.closest("button, input, textarea, label, a, [role='radiogroup']")) {
                        card = null;
                        return;
                    }
                    card = e.target.closest('[class*="st-key-bill_card_"]');
                    startX = e.clientX;
                    startY = e.clientY;
                }, true);
                document.addEventListener("pointerup", function (e) {
                    if (!card) { return; }
                    var current = card;
                    card = null;
                    var dx = e.clientX - startX, dy = e.clientY - startY;
                    if (dx > 90 && Math.abs(dy) < 45 && dx > 2 * Math.abs(dy)) {
                        var idPart = String(current.className).split("st-key-bill_card_")[1];
                        var lineId = idPart ? parseInt(idPart, 10) : NaN;
                        if (isNaN(lineId)) { return; }
                        var button = document.querySelector(".st-key-bill_remove_" + lineId + " button");
                        if (button) { button.click(); }
                    }
                }, true);
                document.addEventListener("pointercancel", function () { card = null; }, true);
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


@st.cache_data(show_spinner=False, ttl=300)
def _suggestions_cached(store_id: int, term: str, _epoch: int) -> dict:
    """What to offer for a typed term, in this order: the store's own stock;
    only if there is none, the medicine list; only if that has none either,
    an "add what you typed" choice."""
    stock = sales_service.search_store_products(store_id, term)
    if stock:
        return {"kind": "stock", "items": stock}
    master = sales_service.search_master_medicines(term)
    if master:
        return {"kind": "master", "items": master}
    is_valid, name = sales_service.is_valid_new_medicine_name(term)
    if is_valid:
        return {"kind": "new", "items": [], "name": name}
    return {"kind": "none", "items": []}


def _render_search(store_id: int) -> None:
    term = _search_box().strip()
    if not term:
        _render_frequently_sold_in_bill(store_id)
        return
    result = _suggestions_cached(store_id, term, get_cache_epoch(store_id))

    if result["kind"] == "stock":
        for index, product in enumerate(result["items"]):
            mrp = bill_service.to_number(product.get("mrp"))
            st.button(
                f"**{product['name']}**\nMRP {_money(mrp)} • Stock: {_stock_text(product['quantity'])}",
                key=f"bill_add_stock_{index}", use_container_width=True,
                on_click=_add_stock_line, args=(store_id, product),
            )
    elif result["kind"] == "master":
        for index, medicine in enumerate(result["items"]):
            detail = medicine.get("composition") or ""
            label = f"**{medicine['name']}**\n{detail}" if detail else f"**{medicine['name']}**"
            st.button(
                label, key=f"bill_add_master_{index}", use_container_width=True,
                on_click=_add_unlisted_line, args=("master", medicine["name"]),
            )
    elif result["kind"] == "new":
        st.button(
            f"➕ Add \"{result['name']}\" as a new medicine",
            key="bill_add_new", use_container_width=True,
            on_click=_add_unlisted_line, args=("new", result["name"]),
        )
    else:
        st.info("No products match your search.")


@st.cache_data(show_spinner=False, ttl=300)
def _bill_frequently_sold_cached(store_id: int, _epoch: int) -> list:
    return sales_service.get_frequently_sold(store_id)


def _render_frequently_sold_in_bill(store_id: int) -> None:
    """Frequently Sold tiles in Bill mode - tapping adds to the bill."""
    products = _bill_frequently_sold_cached(store_id, get_cache_epoch(store_id))
    if not products:
        return
    st.caption("⭐ Frequently Sold")
    for index, product in enumerate(products):
        mrp = bill_service.to_number(product.get("mrp"))
        st.button(
            f"**{product['name']}**  •  Stock: {_stock_text(product['quantity'])}",
            key=f"bill_freq_{index}",
            use_container_width=True,
            on_click=_add_stock_line,
            args=(store_id, product),
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


def _add_stock_line(store_id: int, product: dict) -> None:
    lines = st.session_state.setdefault(_LINES, [])
    existing = next((line for line in lines if bill_service.same_medicine(line, "stock", product["name"])), None)
    if existing is not None:
        _change_quantity(existing["id"], 1)
    else:
        unit = st.session_state.get(_UNIT_CHOICE, "Strip")
        lines.append(bill_service.build_stock_line(store_id, _new_line_id(), product, unit))
    # Version bump separately so the search clears without blocking the add
    st.session_state[_SEARCH_VERSION] = st.session_state.get(_SEARCH_VERSION, 0) + 1


def _add_unlisted_line(kind: str, name: str) -> None:
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
    if line.get("pack_from_db"):
        return st.session_state.get(_UNIT_CHOICE, "Strip")
    return "Strip"


def _step(line: dict) -> int:
    """How much - and + change the quantity: one strip (its tablets) or one
    tablet when the pack is known and Tablet is chosen; else 1."""
    if not line.get("pack"):
        return 1
    return 1 if _unit_of(line) == "Tablet" else line["pack"]


def _change_quantity(line_id: int, direction: int) -> None:
    line = _find_line(line_id)
    if line is None:
        return
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
        f"bill_pack_{line_id}",
    ):
        st.session_state.pop(key, None)


def _remove_line(line_id: int) -> None:
    st.session_state[_LINES] = [line for line in st.session_state.get(_LINES, []) if line["id"] != line_id]
    _drop_widget_keys(line_id)


def _clear_bill() -> None:
    for line in st.session_state.get(_LINES, []):
        _drop_widget_keys(line["id"])
    st.session_state[_LINES] = []


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
                on_click=_set_unit, args=(line_id, "Strip"),
            )
        with mrp_col:
            if mrp <= 0 or editing:
                st.button(
                    "✔" if editing else "MRP", key=f"bill_mrp_button_{line_id}",
                    use_container_width=True, on_click=_toggle_mrp_editor, args=(line_id,),
                )
        with tablet_col:
            st.button(
                "Tablet", key=f"bill_utab_{line_id}", use_container_width=True,
                type="primary" if unit == "Tablet" else "secondary",
                on_click=_set_unit, args=(line_id, "Tablet"),
            )


def _render_pack_input(line: dict) -> None:
    """Tablet is chosen but the system does not know the pack: ask how many
    tablets one strip holds. Until it is entered the line stays in strips;
    after that it works like any medicine with a known pack."""
    if line.get("pack_from_db") or _unit_of(line) != "Tablet":
        return
    value = st.number_input(
        "Ek strip / pack mein kitni tablet?", min_value=2, step=1, value=line.get("pack"),
        placeholder="jaise 10", key=f"bill_pack_{line['id']}",
    )
    if value and int(value) != line.get("pack"):
        bill_service.apply_pack(line, int(value))


def _render_line(line: dict) -> None:
    """One medicine, laid out like a Quick Setup block: square - and + on both
    sides, the name in the middle with MRP / Rate, the quantity big under it.
    Strip / Tablet sit above - and +. Swipe the block right to remove it."""
    line_id = line["id"]
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

    total = bill_service.bill_total(lines)
    without_mrp = sum(1 for line in lines if bill_service.to_number(line.get("mrp")) <= 0)
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
                f"Sell all • {_money(total)}", key="bill_sell_all", type="primary", use_container_width=True,
            )
        with bill_col:
            st.button("🧾 Bill", key="bill_open_form", use_container_width=True, on_click=_toggle_bill_form)
    st.button("🗑️ Bill khali karo", key="bill_clear", use_container_width=True, on_click=_clear_bill)

    if st.session_state.get(_FORM_OPEN):
        _render_bill_form(store_id, lines)

    if sell_clicked:
        names = {line["id"]: line["name"] for line in lines}
        result = bill_service.sell_bill(store_id, lines)
        sold_ids = set(result["sold"])
        sold_total = bill_service.bill_total([line for line in lines if line["id"] in sold_ids])
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
def _seal_cached(store_id: int, _epoch: int):
    try:
        return billing_service.get_seal_sign(store_id)
    except Exception:
        return None          # a missing seal must never stop billing


def _render_bill_form(store_id: int, lines: list) -> None:
    """The bill under the buttons: medicines with MRP and amount, the total,
    an optional customer name and the store's seal / sign. Print sells the
    medicines exactly like Sell all and then opens the print window."""
    if st.session_state.pop("bill_reset_customer", False):
        st.session_state.pop("bill_customer_name", None)     # a new bill starts without the old name
    st.markdown("**🧾 Bill**")
    customer = st.text_input("Customer ka naam (optional)", key="bill_customer_name")
    store_name = get_current_store_name()
    seal_uri = _seal_cached(store_id, get_cache_epoch(store_id))
    st.markdown(
        billing_service.build_bill_body_html(store_name, lines, customer, seal_uri),
        unsafe_allow_html=True,
    )
    if not seal_uri:
        st.caption("Seal / sign abhi upload nahi hui - Quick Setup mein Upload tab se upload karo.")
    if st.button("🖨️ Print", key="bill_print", type="primary", use_container_width=True):
        _sell_and_print(store_id, lines, customer, seal_uri, store_name)


def _sell_and_print(store_id: int, lines: list, customer: str, seal_uri, store_name: str) -> None:
    """Sell every line (same as Sell all), then print ONLY what was sold."""
    names = {line["id"]: line["name"] for line in lines}
    result = bill_service.sell_bill(store_id, lines)
    sold_ids = set(result["sold"])
    sold_lines = [line for line in lines if line["id"] in sold_ids]
    if sold_lines:
        st.session_state[_PRINT] = billing_service.build_print_document(
            store_name, sold_lines, customer, seal_uri,
        )
    for line_id in sold_ids:
        _drop_widget_keys(line_id)
    remaining = [line for line in lines if line["id"] not in sold_ids]
    st.session_state[_LINES] = remaining
    if not remaining:
        st.session_state["bill_reset_customer"] = True
    st.session_state[_FLASH] = {
        "sold_count": len(sold_ids),
        "sold_total": bill_service.bill_total(sold_lines),
        "errors": [f"{names[line_id]}: {message}" for line_id, message in result["failed"].items()],
    }
    bump_cache_epoch(store_id)
    st.rerun()


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