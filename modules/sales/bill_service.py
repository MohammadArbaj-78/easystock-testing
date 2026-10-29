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

from core import name_matching
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
    pack = line.get("pack") or line.get("pack_guess")
    if pack and int(pack) >= 2:
        return format_tablets(line["qty"], int(pack))
    return str(line["qty"])


def line_amount(line: dict) -> float:
    mrp = to_number(line.get("mrp"))
    pack = line.get("pack") or line.get("pack_guess")
    if pack and int(pack) >= 2:
        return round(mrp * line["qty"] / int(pack), 2)
    return round(mrp * line["qty"], 2)


def bill_total(lines: list) -> float:
    return round(sum(line_amount(line) for line in lines), 2)


def same_medicine(line: dict, kind: str, name: str) -> bool:
    return line["kind"] == kind and name_matching.normalized_name(line["name"]) == name_matching.normalized_name(name)


def build_stock_line(store_id: int, line_id: int, product: dict, unit: str = "Strip") -> dict:
    """A bill line for a medicine that is in stock.

    Args:
        product: A row from sales_service.search_store_products (the
            oldest batch with stock) - its MRP and rate are used.
        unit: "Strip" or "Tablet" - what the first + will add, so the
            starting quantity is one strip or one tablet.
    """
    info = sales_service.get_tablet_stock(store_id, product["name"])
    if info is not None:
        pack, units = info["pack"], info["tablets"]
        qty = min(pack if unit == "Strip" else 1, units)
    else:
        pack = None
        units = int(math.floor(to_number(sales_service.get_sellable_stock(store_id, product["name"])) + 1e-9))
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
        "stock_units": units,
        "qty": max(1, qty),
    }


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

def sell_bill(store_id: int, lines: list) -> dict:
    """Sell every line, one after the other.

    A line that cannot be sold (not enough stock, a database problem) does
    NOT stop the others: it is reported and stays on the bill, and the lines
    already sold stay sold. Nothing is sold twice because the caller removes
    exactly the lines reported as sold.

    Returns:
        {"sold": [line ids], "failed": {line id: message}}
    """
    sold, failed = [], {}
    for line in lines:
        try:
            _sell_line(store_id, line)
            sold.append(line["id"])
        except ValidationError as error:
            failed[line["id"]] = str(error)
        except Exception as error:
            failed[line["id"]] = f"Could not sell this: {error}"
    return {"sold": sold, "failed": failed}


def _sell_line(store_id: int, line: dict) -> None:
    qty = line["qty"]
    if line["kind"] == "stock":
        if line.get("pack"):
            sales_service.sell_tablets(store_id, line["product_id"], qty)
        else:
            sales_service.sell_product(store_id, line["product_id"], qty)
        return
    _sell_unlisted_line(store_id, line)


def _sell_unlisted_line(store_id: int, line: dict) -> None:
    """Sell a medicine that was not in the store's stock when it was added
    to the bill.

    If it has been added to the stock since, it is sold from that stock like
    any other. Otherwise it is first put into the system - name, the MRP the
    owner set, and exactly the quantity being sold - and then sold, so the
    system ends up knowing the medicine with 0 in stock and the sale is in
    the history. The real stock count is set later (an invoice scan or Quick
    Setup); nothing here guesses it.
    """
    from modules.products import service as products_service
    from modules.quick_setup import service as quick_setup_service

    name = name_matching.clean_spaces(line["name"])
    qty = line["qty"]

    wanted = name_matching.normalized_name(name)
    for product in sales_service.search_store_products(store_id, name):
        if name_matching.normalized_name(product["name"]) == wanted:
            sales_service.sell_product(store_id, product["product_id"], qty)
            return

    quick_setup_service.save_quantities(store_id, {name: qty})
    row = products_service.find_quick_setup_placeholder_by_name(store_id, name)
    if row is None:
        raise ValidationError("This medicine could not be added to the system.")

    mrp = to_number(line.get("mrp"))
    if mrp > 0:
        data = {
            key: row.get(key)
            for key in (
                "name", "batch_number", "expiry_date", "quantity", "rate",
                "gst_percent", "purchase_date", "minimum_stock_threshold",
            )
        }
        data["mrp"] = mrp
        products_repository.update_product(store_id, row["product_id"], data)

    sales_service.sell_product(store_id, row["product_id"], qty)