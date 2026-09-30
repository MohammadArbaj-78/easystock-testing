"""
Agencies service - business logic for the agencies ledger.

No SQL here - everything goes through modules.agencies.repository. This
file's job is validation and the small pieces of logic that shouldn't
live in the UI or the repository: deciding whether an invoice header is
complete enough to record as a bill, and validating a payment amount.
"""

from modules.agencies import repository as agencies_repository


def record_bill_from_invoice_header(store_id: int, invoice_header: dict) -> dict:
    """Add a bill to the agency ledger from a saved invoice's header
    fields, creating the agency if it doesn't exist yet.

    Called once, from modules.invoice_scan.review_service.save_invoice_medicines(),
    every time the store owner clicks "Save Medicines" - regardless of
    how many (if any) medicine rows were actually saved, since the
    money owed to the agency is real either way.

    Never raises: a bill with no readable agency name or total simply
    is not recorded (the store owner already saw a "required" warning
    for these in the Review screen before saving, via
    review_service.validate_invoice_header) - it must never block
    medicines from being saved.

    Args:
        store_id: The current store.
        invoice_header: {"agency_name", "invoice_date", "grand_total"}
            as produced by modules.invoice_scan.ocr_service and
            possibly edited by the store owner.

    Returns:
        {"recorded": True, "agency_id": int, "agency_name": str,
         "grand_total": float} on success, or
        {"recorded": False, "reason": str} if the agency name or total
        was missing/invalid.
    """
    agency_name = str((invoice_header or {}).get("agency_name") or "").strip()
    if not agency_name:
        return {"recorded": False, "reason": "No agency name."}

    grand_total = _parse_positive_amount((invoice_header or {}).get("grand_total"))
    if grand_total is None:
        return {"recorded": False, "reason": "No valid grand total."}

    invoice_date = str((invoice_header or {}).get("invoice_date") or "").strip()

    agency_id = agencies_repository.find_or_create_agency(store_id, agency_name)
    agencies_repository.add_bill(store_id, agency_id, invoice_date, grand_total)

    return {
        "recorded": True,
        "agency_id": agency_id,
        "agency_name": agency_name,
        "grand_total": grand_total,
    }


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