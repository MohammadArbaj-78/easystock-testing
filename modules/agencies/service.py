"""
Agencies service - business logic for the agencies ledger.

No SQL here - everything goes through modules.agencies.repository. This
file's job is validation and the small pieces of logic that shouldn't
live in the UI or the repository: deciding whether an invoice header is
complete enough to record as a bill, and validating a payment amount.
"""

import logging
import math

from modules.agencies import repository as agencies_repository

logger = logging.getLogger(__name__)


def record_bill_from_invoice_header(
    store_id: int,
    invoice_header: dict,
    image_bytes: bytes = None,
    image_content_type: str = None,
) -> dict:
    """Add a bill to the agency ledger from a saved invoice's header
    fields, creating the agency if it doesn't exist yet.

    Never raises: a bill with no readable agency name or total simply
    is not recorded. The photo upload (if any) is likewise best-effort
    - see core.supabase_storage.upload_invoice_image - a failed photo
    upload never blocks or fails the bill itself.
    """
    agency_name = str((invoice_header or {}).get("agency_name") or "").strip()
    if not agency_name:
        return {"recorded": False, "reason": "No agency name."}

    grand_total = _parse_positive_amount((invoice_header or {}).get("grand_total"))
    if grand_total is None:
        return {"recorded": False, "reason": "No valid grand total."}

    invoice_date = str((invoice_header or {}).get("invoice_date") or "").strip()

    image_path = None
    if image_bytes:
        from core.supabase_storage import upload_invoice_image
        image_path = upload_invoice_image(store_id, image_bytes, image_content_type)

    agency_id = agencies_repository.find_or_create_agency(store_id, agency_name)
    bill_id = agencies_repository.add_bill(
        store_id, agency_id, invoice_date, grand_total,
        image_path=image_path,
        image_content_type=image_content_type if image_path else None,
    )

    return {
        "recorded": True,
        "agency_id": agency_id,
        "bill_id": bill_id,
        "agency_name": agency_name,
        "grand_total": grand_total,
    }

def record_invoice_medicines(
    store_id: int,
    invoice_header: dict,
    medicines: list,
    agency_id: int = None,
    bill_id: int = None,
) -> dict:
    """Keep the medicines of a saved invoice under the agency they were
    bought from (table agency_medicines), exactly as scanned/reviewed:
    name, batch number, quantity, expiry date, MRP, rate. Anything blank
    or not a number is stored as empty (NULL).

    Every row that has a name is kept - it is a record of what the bill
    contained, independent of what happened to the stock. Nothing reads
    this table yet (a screen for it can be added later).

    Never raises: a failure here (for example the table is missing in the
    database) must never stop the medicines from being saved to stock.

    Args:
        agency_id / bill_id: From the ledger entry of the same save, if
            one was recorded. Without agency_id the agency is looked up
            (or created) from the invoice header's agency name.

    Returns:
        {"recorded": <rows kept>} or {"recorded": 0, "reason"/"error": ...}
    """
    try:
        rows = [
            cleaned for cleaned in (_clean_medicine_row(m) for m in (medicines or []))
            if cleaned is not None
        ]
        if not rows:
            return {"recorded": 0, "reason": "No medicines."}

        if agency_id is None:
            agency_name = str((invoice_header or {}).get("agency_name") or "").strip()
            if not agency_name:
                return {"recorded": 0, "reason": "No agency name."}
            agency_id = agencies_repository.find_or_create_agency(store_id, agency_name)

        count = agencies_repository.add_invoice_medicines(store_id, agency_id, bill_id, rows)
        return {"recorded": count}
    except Exception as exc:  # best effort by design - see docstring
        logger.warning("Could not keep the invoice medicines under the agency: %s", exc)
        return {"recorded": 0, "error": str(exc)}


def _clean_medicine_row(medicine: dict):
    """One reviewed medicine row -> the row to keep, or None if it has no name."""
    name = str((medicine or {}).get("name") or "").strip()
    if not name:
        return None

    def text(key):
        value = str(medicine.get(key) or "").strip()
        return value or None

    return {
        "name": name,
        "batch_number": text("batch_number"),
        "quantity": _number_or_none(medicine.get("quantity")),
        "expiry_date": text("expiry_date"),
        "mrp": _number_or_none(medicine.get("mrp")),
        "rate": _number_or_none(medicine.get("rate")),
        "product_id": medicine.get("product_id"),
    }


def _number_or_none(value):
    """A typed/scanned number as a float (a whole number as an int), or None
    when it is blank, not a number, or negative."""
    text = str(value if value is not None else "").replace("₹", "").replace(",", "").strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number) or number < 0:
        return None
    return int(number) if number == int(number) else number


def get_agency_ledger(store_id: int) -> list:
    """Return every agency for this store with its running balance.

    Returns:
        List of {"agency_id", "agency_name", "total_billed",
        "total_paid", "balance"}, sorted by agency_name.
    """
    return agencies_repository.get_agencies_with_balance(store_id)


def get_agency_detail(store_id: int, agency_id: int) -> dict:
    """Return one agency's bills and payments, newest first, plus its
    running balance.

    Returns:
        {"bills": [...], "payments": [...], "total_billed": float,
         "total_paid": float, "balance": float}
    """
    bills = agencies_repository.get_bills_for_agency(store_id, agency_id)
    payments = agencies_repository.get_payments_for_agency(store_id, agency_id)
    total_billed = sum(bill["grand_total"] for bill in bills)
    total_paid = sum(payment["amount"] for payment in payments)
    return {
        "bills": bills,
        "payments": payments,
        "total_billed": total_billed,
        "total_paid": total_paid,
        "balance": total_billed - total_paid,
    }


def get_all_agency_details(store_id: int) -> dict:
    """The same information as get_agency_detail() for EVERY agency, from
    two queries in total (the Agencies screen used to run two per
    agency). Newest first.

    Returns:
        {agency_id: {"bills", "payments", "total_billed", "total_paid",
        "balance"}} - only for agencies that have a bill or payment.
    """
    details = {}

    def entry(agency_id):
        return details.setdefault(agency_id, {"bills": [], "payments": []})

    for bill in agencies_repository.get_bills_for_store(store_id):
        entry(bill["agency_id"])["bills"].append(bill)
    for payment in agencies_repository.get_payments_for_store(store_id):
        entry(payment["agency_id"])["payments"].append(payment)
    for detail in details.values():
        detail["total_billed"] = sum(b["grand_total"] for b in detail["bills"])
        detail["total_paid"] = sum(p["amount"] for p in detail["payments"])
        detail["balance"] = detail["total_billed"] - detail["total_paid"]
    return details


def get_agency_medicines_by_agency(store_id: int) -> dict:
    """The medicines of every agency, as the store's LIVE product rows.

    The agency_medicines rows only say which medicine came with which
    agency's bill; what is shown (qty, MRP, expiry ...) is always the
    current product row, so editing or deleting a product on the
    Products screen shows here too. A kept row is linked to its product
    by product_id, or - for rows kept without one - by name + batch +
    expiry. A row whose product no longer exists is not shown. A product
    bought from several agencies is shown under the one it was bought
    from most recently.

    Returns:
        {agency_id: [product dict, ...]}, each list sorted by name.
    """
    from modules.products import service as products_service

    rows = agencies_repository.get_medicine_rows_for_store(store_id)
    if not rows:
        return {}

    products = products_service.search_products(store_id)
    by_id = {product["product_id"]: product for product in products}
    by_lot = {}
    for product in sorted(products, key=lambda item: item["product_id"], reverse=True):
        by_lot[_lot_key(product.get("name"), product.get("batch_number"), product.get("expiry_date"))] = product

    result, seen = {}, set()
    for row in rows:                      # newest first
        product_id = row.get("product_id")
        if product_id is not None:
            product = by_id.get(product_id)
        else:
            product = by_lot.get(_lot_key(row.get("name"), row.get("batch_number"), row.get("expiry_date")))
        if product is None or product["product_id"] in seen:
            continue
        seen.add(product["product_id"])
        result.setdefault(row["agency_id"], []).append(product)

    for items in result.values():
        items.sort(key=lambda item: str(item.get("name") or "").lower())
    return result


def search_agency_medicines(products: list, search_term: str = None, limit: int = 10) -> dict:
    """First `limit` of an agency's medicines (name or batch contains the
    search text, any case) plus how many matched."""
    term = str(search_term or "").strip().lower()
    if term:
        products = [
            item for item in products
            if term in str(item.get("name") or "").lower()
            or term in str(item.get("batch_number") or "").lower()
        ]
    return {"items": products[:limit], "total": len(products)}


def _lot_key(name, batch, expiry) -> tuple:
    return (
        str(name or "").strip().lower(),
        str(batch or "").strip().lower(),
        str(expiry or "").strip(),
    )


def record_payment(store_id: int, agency_id: int, amount, paid_on: str = None) -> dict:
    """Record a payment made to an agency.

    Args:
        store_id: The current store.
        agency_id: The agency being paid.
        amount: The amount paid, as typed by the store owner (string or
            number) - must parse to a number greater than 0.
        paid_on: Optional date string the store owner typed in.

    Returns:
        {"recorded": True, "payment_id": int, "amount": float} or
        {"recorded": False, "reason": str} if the amount was invalid.
    """
    parsed_amount = _parse_positive_amount(amount)
    if parsed_amount is None:
        return {"recorded": False, "reason": "Enter a valid amount greater than 0."}

    payment_id = agencies_repository.add_payment(store_id, agency_id, parsed_amount, paid_on)
    return {"recorded": True, "payment_id": payment_id, "amount": parsed_amount}


def _parse_positive_amount(value) -> float:
    """Parse a rupee amount ("1515", "1,515.50", "₹ 1515.5") into a
    float, or return None if it is empty, not a number, or not greater
    than zero. Same cleaning rule as
    modules.invoice_scan.review_service.parse_amount, kept as its own
    copy here so this module has no dependency on invoice_scan.
    """
    cleaned = str(value or "").strip()
    for junk in ("₹", "Rs.", "Rs", "INR", ",", " "):
        cleaned = cleaned.replace(junk, "")
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return number if number > 0 else None