"""Bill mode of the Sales screen: several medicines in one list, one total,
one Sell button.

This file holds everything that is not drawing: building a bill line, the
amount of a line and of the whole bill, and selling the lines. It reuses the
selling that already exists (sell_product, sell_tablets) and does not change
it. The screen is modules/sales/bill_ui.py.

A bill line is a plain dict:
    id         number, unique inside the bill
    kind       "stock"  - a medicine that is in the store's stock
               "master" - picked from the medicine list, NOT in the store yet
               "new"    - typed by the owner, found nowhere
    name       the medicine name
    product_id (stock lines) the batch row it was picked from
    mrp        price of one STRIP / pack as a number; 0 = not known yet
    rate       what the store paid (shown only, never used in the total)
    pack       tablets per strip if known (then qty is in TABLETS), else None
    stock_units how many can be sold (tablets if pack, else strips); None =
               no limit (medicine not in stock)
    qty        whole number, in TABLETS when pack is known, else in STRIPS
"""

import math
from concurrent.futures import ThreadPoolExecutor

from core import name_matching
from config.settings import ACTIVE_DB_BACKEND
from core.exceptions import ValidationError
from modules.products import repository as products_repository
from modules.sales import service as sales_service


def to_number(value) -> float:
    """A price / quantity as a float; 0.0 for None, blank or text."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def format_tablets(tablets: int, pack: int) -> str:
    """Tablets as strips + loose tablets: 28 of a 15-pack -> "1 strip + 13
    tablets"; 30 -> "2 strips"; 10 -> "10 tablets". Never a decimal."""
    strips, loose = divmod(int(tablets), int(pack))
    parts = []
    if strips:
        parts.append(f"{strips} strip" + ("" if strips == 1 else "s"))
    if loose or not parts:
        parts.append(f"{loose} tablet" + ("" if loose == 1 else "s"))
    return " + ".join(parts)


def quantity_text(line: dict) -> str:
    pack = line.get("pack")
    if pack:
        return format_tablets(line["qty"], pack)
    return str(line["qty"])


def money(amount: float) -> str:
    """₹1,234.5 - two decimals only where they are needed."""
    text = f"{amount:,.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"₹{text}"


def get_lots(store_id: int, name: str) -> list:
    """Every in-stock lot (batch) of a medicine, oldest arrival first - the
    same FIFO order the sale itself uses."""
    from modules.products.service import get_lots_by_name_sorted_by_expiry
    return get_lots_by_name_sorted_by_expiry(store_id, name)


def line_pieces(line: dict) -> list:
    """FIFO split of a line: [(units, MRP of one strip), ...]. The sale takes
    stock lot by lot, oldest first, so each lot is priced with its OWN MRP.
    line["lots"] = [(units in the lot, its MRP)] in that order (units =
    tablets if pack is known, else strips). A lot with no MRP, and anything
    beyond the known lots (a medicine not in stock), uses the line's MRP -
    the one the owner can set."""
    fallback = to_number(line.get("mrp"))
    remaining = line["qty"]
    pieces = []
    for units, lot_mrp in (line.get("lots") or []):
        if remaining <= 0:
            break
        take = min(units, remaining)
        if take <= 0:
            continue
        pieces.append((take, lot_mrp if lot_mrp > 0 else fallback))
        remaining -= take
    if remaining > 0:
        pieces.append((remaining, fallback))
    return pieces


def line_amount(line: dict) -> float:
    """Every FIFO lot at its own MRP (loose tablets cost MRP / pack each)."""
    pack = line.get("pack")
    total = 0.0
    for units, mrp in line_pieces(line):
        total += mrp * units / pack if pack else mrp * units
    return round(total, 2)


def line_mrp_text(line: dict) -> str:
    """The MRP(s) the line is priced with: "₹70" or "₹70 / ₹45"."""
    seen = []
    for _units, mrp in line_pieces(line):
        if mrp > 0 and mrp not in seen:
            seen.append(mrp)
    return " / ".join(money(mrp) for mrp in seen)


def apply_pack(line: dict, pack: int) -> None:
    """The owner told how many tablets one strip holds (a medicine whose
    pack the system does not know). From now the line counts in tablets. For
    a medicine in stock the pack is saved on it when the bill is sold - tablet
    selling needs it."""
    first = not line.get("pack")
    line["pack"] = pack
    if line["kind"] == "stock":
        line["lots"] = [(int(round(strips * pack)), mrp) for strips, mrp in line["raw_lots"]]
        line["stock_units"] = sum(units for units, _mrp in line["lots"])
        line["pack_new"] = True
    if first:
        # Strips the owner already set stay: 3 strips become 3 x pack tablets.
        # If the quantity was never touched (still the default 1), start from
        # one tablet.
        line["qty"] = line["qty"] * pack if line.get("qty_touched") else 1
    if line.get("stock_units") is not None and line["stock_units"] >= 1:
        line["qty"] = max(1, min(line["qty"], line["stock_units"]))


def bill_total(lines: list) -> float:
    return round(sum(line_amount(line) for line in lines), 2)


def same_medicine(line: dict, kind: str, name: str) -> bool:
    return line["kind"] == kind and name_matching.normalized_name(line["name"]) == name_matching.normalized_name(name)


def build_stock_line(store_id: int, line_id: int, product: dict, unit: str = "Strip") -> dict:
    """A bill line for a medicine that is in stock.

    Args:
        product: A row from sales_service.search_store_products (the oldest
            batch with stock). It carries every lot under "lots"; if not,
            they are read here (one lookup).
        unit: "Strip" or "Tablet" - what the first + will add.
    """
    lots = product.get("lots") or get_lots(store_id, product["name"])
    pack = sales_service._common_pack(lots)
    raw_lots = [(to_number(lot["quantity"]), to_number(lot.get("mrp"))) for lot in lots]
    if pack:
        lot_units = [(int(round(strips * pack)), mrp) for strips, mrp in raw_lots]
        units = sum(count for count, _mrp in lot_units)
        qty = min(pack if unit == "Strip" else 1, units)
    else:
        lot_units = [(int(math.floor(strips + 1e-9)), mrp) for strips, mrp in raw_lots]
        units = int(math.floor(sum(strips for strips, _mrp in raw_lots) + 1e-9))
        qty = 1
    rate = to_number(product.get("rate"))
    return {
        "id": line_id,
        "kind": "stock",
        "name": product["name"],
        "product_id": product["product_id"],
        "mrp": to_number(product.get("mrp")),
        "rate": rate if rate > 0 else None,
        "pack": pack,
        "pack_from_db": bool(pack),
        "stock_units": units,
        "lots": lot_units,
        "raw_lots": raw_lots,
        "qty": max(1, qty),
    }

def zero_stock_matches(catalog: list, term: str, limit: int = 5) -> list:
    """Medicines the store HAS in its system but with no stock left (every lot
    at 0) whose name contains what was typed - e.g. one that was added by a
    Bill sale. One row per medicine: the newest lot that has an MRP. The
    medicines that are in stock are not in this list (they are offered as
    usual)."""
    words = (term or "").lower().split()
    if not words:
        return []
    by_name = {}
    for row in catalog:
        name = str(row.get("name") or "")
        if name and all(word in name.lower() for word in words):
            by_name.setdefault(name_matching.normalized_name(name), []).append(row)
    found = []
    for rows in by_name.values():
        if any(to_number(row.get("quantity")) > 0 for row in rows):
            continue
        found.append(max(rows, key=lambda row: (to_number(row.get("mrp")) > 0, row["product_id"])))
    found.sort(key=lambda row: row["name"].lower())
    return found[:limit]


def build_zero_line(line_id: int, product: dict, unit: str = "Strip") -> dict:
    """A bill line for a medicine that is in the system with 0 stock. It works
    exactly like a medicine that is not in the system (no stock limit; selling
    adds the quantity and sells it, so it stays at 0), but its MRP and pack
    size are already filled from the system."""
    line = build_unlisted_line(line_id, "zero", product["name"])
    line["mrp"] = to_number(product.get("mrp"))
    rate = to_number(product.get("rate"))
    line["rate"] = rate if rate > 0 else None
    pack = int(round(to_number(product.get("pack_size"))))
    if pack >= 2:
        line["pack"] = pack
        line["pack_from_db"] = True
        line["qty"] = pack if unit == "Strip" else 1
    return line

def build_unlisted_line(line_id: int, kind: str, name: str) -> dict:
    """A bill line for a medicine that is not in the store's stock yet
    (kind "master" or "new"). Its MRP starts at 0 - the owner sets it."""
    return {
        "id": line_id,
        "kind": kind,
        "name": name_matching.clean_spaces(name),
        "product_id": None,
        "mrp": 0.0,
        "rate": None,
        "pack": None,
        "stock_units": None,
        "qty": 1,
    }


# ---------------------------------------------------------------------------
# Selling
# ---------------------------------------------------------------------------

# How many medicines of one bill are sold side by side (Supabase only: each sale
# is several network calls, so a bill of 6 medicines would wait 6 times as long
# one by one). 1 = one after the other, as before.
_PARALLEL_SELL_WORKERS = 4


def _attempt_sale(store_id: int, line: dict):
    """Sell one line; None if it worked, else the message why it did not."""
    if to_number(line.get("mrp")) <= 0:
        return "MRP daalo - bina MRP ke bech nahi sakte."
    try:
        _sell_line(store_id, line)
        return None
    except ValidationError as error:
        return str(error)
    except Exception as error:
        return f"Could not sell this: {error}"


def sell_bill(store_id: int, lines: list) -> dict:
    """Sell every line.

    A line that cannot be sold (not enough stock, a database problem) does
    NOT stop the others: it is reported and stays on the bill, and the lines
    already sold stay sold. Nothing is sold twice because the caller removes
    exactly the lines reported as sold.

    Lines of medicines that are in stock touch only their own medicine's
    batches, so (on Supabase) several of them are sold side by side. Medicines
    that are not in the system yet are added and sold one after the other.

    Returns:
        {"sold": [line ids], "failed": {line id: message}}
    """
    outcome = {}
    stock_lines = [line for line in lines if line["kind"] == "stock"]
    names = {name_matching.normalized_name(line["name"]) for line in stock_lines}
    if (
        ACTIVE_DB_BACKEND == "supabase" and _PARALLEL_SELL_WORKERS > 1
        and len(stock_lines) > 1 and len(names) == len(stock_lines)
    ):
        workers = min(_PARALLEL_SELL_WORKERS, len(stock_lines))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for line, message in zip(stock_lines, pool.map(lambda line: _attempt_sale(store_id, line), stock_lines)):
                outcome[line["id"]] = message
    for line in lines:                       # everything not sold above, one after the other
        if line["id"] not in outcome:
            outcome[line["id"]] = _attempt_sale(store_id, line)

    sold, failed = [], {}
    for line in lines:
        message = outcome[line["id"]]
        if message is None:
            sold.append(line["id"])
        else:
            failed[line["id"]] = message
    return {"sold": sold, "failed": failed}

def _sell_line(store_id: int, line: dict) -> None:
    qty = line["qty"]
    if line["kind"] == "stock":
        if line.get("pack"):
            if line.get("pack_new"):
                _save_pack_on_lots(store_id, line["name"], line["pack"])
            sales_service.sell_tablets(store_id, line["product_id"], qty)
        else:
            sales_service.sell_product(store_id, line["product_id"], qty)
        return
    _sell_unlisted_line(store_id, line)


def _save_pack_on_lots(store_id: int, name: str, pack: int) -> None:
    """Store the pack size (tablets per strip) the owner gave on every lot of
    the medicine - tablet-wise stock needs it. Nothing else is changed."""
    for lot in get_lots(store_id, name):
        data = {
            key: lot.get(key)
            for key in (
                "name", "batch_number", "expiry_date", "quantity", "rate", "gst_percent",
                "purchase_date", "minimum_stock_threshold", "mrp",
            )
        }
        data["pack_size"] = pack
        products_repository.update_product(store_id, lot["product_id"], data)


def _sell_unlisted_line(store_id: int, line: dict) -> None:
    """Sell a medicine that was not in the store's stock when it was added.

    If it has been added to the stock since, it is sold from that stock like
    any other. Otherwise it is first put into the system - name, the MRP the
    owner set, the pack size if it is sold by the tablet, and exactly the
    quantity being sold - and then sold, so the system knows the medicine with
    0 in stock and the sale is in the history.
    """
    from modules.products import service as products_service
    from modules.quick_setup import service as quick_setup_service

    name = name_matching.clean_spaces(line["name"])
    qty = line["qty"]
    pack = line.get("pack")          # tablets per strip, when the owner gave it

    wanted = name_matching.normalized_name(name)
    for product in sales_service.search_store_products(store_id, name):
        if name_matching.normalized_name(product["name"]) == wanted:
            if pack:
                sales_service.sell_tablets(store_id, product["product_id"], qty)
            else:
                sales_service.sell_product(store_id, product["product_id"], qty)
            return

    # Stock is kept in strips: tablets are a part of a strip.
    quick_setup_service.save_quantities(store_id, {name: (qty / pack) if pack else qty})
    row = products_service.find_quick_setup_placeholder_by_name(store_id, name)
    if row is None:
        raise ValidationError("This medicine could not be added to the system.")

    mrp = to_number(line.get("mrp"))
    if mrp > 0 or pack:
        data = {
            key: row.get(key)
            for key in (
                "name", "batch_number", "expiry_date", "quantity", "rate",
                "gst_percent", "purchase_date", "minimum_stock_threshold",
            )
        }
        data["mrp"] = mrp if mrp > 0 else row.get("mrp")
        if pack:
            data["pack_size"] = pack
        products_repository.update_product(store_id, row["product_id"], data)

    if pack:
        sales_service.sell_tablets(store_id, row["product_id"], qty)
    else:
        sales_service.sell_product(store_id, row["product_id"], qty)