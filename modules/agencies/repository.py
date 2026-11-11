"""
Agencies repository - data access layer for the agencies, agency_bills
and agency_payments tables.

An "agency" here is a distributor/wholesaler a store buys medicines
from. The running balance owed to an agency is never stored as a
column anywhere - it is always computed at read time as
(total billed - total paid), so it can never drift out of sync with
the bills/payments actually recorded. This mirrors sales_history's
append-only design: bills and payments are only ever inserted, never
updated or deleted, so the ledger is always a plain, auditable sum of
real entries.

Every function takes store_id as its first required argument, sourced
by the calling service from core.session.get_current_store_id(), same
as every other repository in this codebase.

--- Dual-backend, following modules/products/repository.py's pattern ---
Every public function is a thin dispatcher on ACTIVE_DB_BACKEND
(imported from config/settings.py, never defined here). The Supabase
implementations use the shared client from core.supabase_client
(imported lazily, so importing this module - or running the SQLite
path - never requires the `supabase`/`streamlit` packages to be
installed).
"""

import re

from core.database import get_connection
from config.settings import ACTIVE_DB_BACKEND


def normalize_agency_name(agency_name: str) -> str:
    """Turn an agency name into a comparison key: lowercased, extra
    whitespace collapsed, leading/trailing whitespace trimmed.

    This is what makes "Sharma Pharma", " sharma  pharma ", and
    "SHARMA PHARMA" all resolve to the SAME agency instead of each
    creating a separate one. It intentionally does NOT strip
    punctuation or business-entity suffixes ("Pvt Ltd", "& Co.") - two
    genuinely different registered names are kept as two different
    agencies rather than guessing they're the same business.
    """
    return re.sub(r"\s+", " ", (agency_name or "").strip().lower())


# =====================================================================
# Public API - dispatchers
# =====================================================================

def find_or_create_agency(store_id: int, agency_name: str) -> int:
    """Return the agency_id for this store + agency name, creating a
    new agency row if no existing one matches (by normalized name).

    Args:
        store_id: The current store.
        agency_name: The agency name as read from the invoice (or typed
            in by the store owner). Must not be blank.

    Returns:
        The existing or newly created agency_id.

    Raises:
        DatabaseError: If the insert/lookup fails.
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _find_or_create_agency_supabase(store_id, agency_name)
    return _find_or_create_agency_sqlite(store_id, agency_name)


def add_bill(store_id: int, agency_id: int, invoice_date: str, grand_total: float, image_path: str = None, image_content_type: str = None,) -> int:
    """Insert one bill row against an agency. The only write this file
    performs to agency_bills.

    Args:
        store_id: The current store.
        agency_id: From find_or_create_agency().
        invoice_date: The bill date as printed/typed - free text, not
            parsed into a real date (invoices use many different
            formats and are often handwritten) - it is a DISPLAY
            label, never used for sorting (see get_bills_for_agency).
        grand_total: The bill's total amount. Must be > 0.

    Returns:
        The newly created bill_id.
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _add_bill_supabase(store_id, agency_id, invoice_date, grand_total, image_path, image_content_type)
    return _add_bill_sqlite(store_id, agency_id, invoice_date, grand_total, image_path, image_content_type)

def add_invoice_medicines(store_id: int, agency_id: int, bill_id, medicines: list) -> int:
    """Insert the medicines of one scanned bill against an agency (table
    agency_medicines). Append-only, like bills and payments.

    Args:
        store_id: The current store.
        agency_id: From find_or_create_agency().
        bill_id: The bill these medicines came with, or None if no bill
            was recorded for the invoice.
        medicines: Already cleaned rows - dicts with name, batch_number,
            quantity, expiry_date, mrp, rate (blank values are None).

    Returns:
        How many rows were inserted.
    """
    if not medicines:
        return 0
    if ACTIVE_DB_BACKEND == "supabase":
        return _add_invoice_medicines_supabase(store_id, agency_id, bill_id, medicines)
    return _add_invoice_medicines_sqlite(store_id, agency_id, bill_id, medicines)


def get_bills_for_store(store_id: int) -> list:
    """Every bill of every agency of this store, newest first (each row
    also has agency_id). One query instead of one per agency."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _get_bills_for_store_supabase(store_id)
    return _get_bills_for_store_sqlite(store_id)


def get_payments_for_store(store_id: int) -> list:
    """Every payment of every agency of this store, newest first (each
    row also has agency_id)."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _get_payments_for_store_supabase(store_id)
    return _get_payments_for_store_sqlite(store_id)


def get_medicine_rows_for_store(store_id: int) -> list:
    """Every kept invoice-medicine row of this store, newest first:
    id, agency_id, product_id (may be None), name, batch_number,
    expiry_date."""
    if ACTIVE_DB_BACKEND == "supabase":
        return _get_medicine_rows_for_store_supabase(store_id)
    return _get_medicine_rows_for_store_sqlite(store_id)


def add_payment(store_id: int, agency_id: int, amount: float, paid_on: str = None) -> int:
    """Insert one payment row against an agency. The only write this
    file performs to agency_payments.

    Args:
        store_id: The current store.
        agency_id: The agency being paid.
        amount: The amount paid. Must be > 0.
        paid_on: Optional date string the store owner typed in. If not
            given, defaults to now (see the SQLite/Supabase
            implementations).

    Returns:
        The newly created payment_id.
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _add_payment_supabase(store_id, agency_id, amount, paid_on)
    return _add_payment_sqlite(store_id, agency_id, amount, paid_on)


def get_agencies_with_balance(store_id: int) -> list:
    """Return every agency this store has a bill or payment against,
    each with its running balance.

    Returns:
        List of {"agency_id", "agency_name", "total_billed",
        "total_paid", "balance"}, sorted by agency_name (A-Z).
        balance = total_billed - total_paid (can be 0 or negative if
        the store has overpaid).
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _get_agencies_with_balance_supabase(store_id)
    return _get_agencies_with_balance_sqlite(store_id)


def get_bills_for_agency(store_id: int, agency_id: int) -> list:
    """Return every bill recorded against this agency, newest first.

    Ordered by bill_id (i.e. by when it was SCANNED/saved into
    EasyStock, not by the invoice_date text on the bill) - invoice_date
    is free text in whatever format/language the invoice printed or the
    store owner typed, so it cannot be reliably sorted as a real date.

    Returns:
        List of {"bill_id", "invoice_date", "grand_total", "created_at"}.
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _get_bills_for_agency_supabase(store_id, agency_id)
    return _get_bills_for_agency_sqlite(store_id, agency_id)


def get_payments_for_agency(store_id: int, agency_id: int) -> list:
    """Return every payment recorded against this agency, newest first.

    Returns:
        List of {"payment_id", "amount", "paid_on", "created_at"}.
    """
    if ACTIVE_DB_BACKEND == "supabase":
        return _get_payments_for_agency_supabase(store_id, agency_id)
    return _get_payments_for_agency_sqlite(store_id, agency_id)


# =====================================================================
# SQLite implementation
# =====================================================================

def _find_or_create_agency_sqlite(store_id: int, agency_name: str) -> int:
    normalized = normalize_agency_name(agency_name)
    with get_connection() as connection:
        existing = connection.execute(
            "SELECT agency_id FROM agencies WHERE store_id = ? AND normalized_name = ?",
            (store_id, normalized),
        ).fetchone()
        if existing:
            return existing["agency_id"]

        cursor = connection.execute(
            "INSERT INTO agencies (store_id, agency_name, normalized_name) VALUES (?, ?, ?)",
            (store_id, agency_name.strip(), normalized),
        )
        return cursor.lastrowid


def _add_bill_sqlite(
    store_id: int, agency_id: int, invoice_date: str, grand_total: float,
    image_path: str = None, image_content_type: str = None,
) -> int:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO agency_bills
                (store_id, agency_id, invoice_date, grand_total, image_path, image_content_type)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (store_id, agency_id, invoice_date or "", grand_total, image_path, image_content_type),
        )
        return cursor.lastrowid

_MEDICINE_COLUMNS = ("name", "batch_number", "quantity", "expiry_date", "mrp", "rate", "product_id")


def _medicine_payload(store_id: int, agency_id: int, bill_id, medicine: dict) -> dict:
    payload = {"store_id": store_id, "agency_id": agency_id, "bill_id": bill_id}
    for column in _MEDICINE_COLUMNS:
        payload[column] = medicine.get(column)
    return payload


def _add_invoice_medicines_sqlite(store_id: int, agency_id: int, bill_id, medicines: list) -> int:
    rows = [
        (
            store_id, agency_id, bill_id,
            medicine.get("name"), medicine.get("batch_number"), medicine.get("quantity"),
            medicine.get("expiry_date"), medicine.get("mrp"), medicine.get("rate"),
            medicine.get("product_id"),
        )
        for medicine in medicines
    ]
    with get_connection() as connection:
        connection.executemany(
            """
            INSERT INTO agency_medicines
                (store_id, agency_id, bill_id, name, batch_number, quantity, expiry_date, mrp, rate, product_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


def _add_payment_sqlite(store_id: int, agency_id: int, amount: float, paid_on: str = None) -> int:
    with get_connection() as connection:
        if paid_on:
            cursor = connection.execute(
                "INSERT INTO agency_payments (store_id, agency_id, amount, paid_on) VALUES (?, ?, ?, ?)",
                (store_id, agency_id, amount, paid_on),
            )
        else:
            cursor = connection.execute(
                "INSERT INTO agency_payments (store_id, agency_id, amount) VALUES (?, ?, ?)",
                (store_id, agency_id, amount),
            )
        return cursor.lastrowid


def _get_agencies_with_balance_sqlite(store_id: int) -> list:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                a.agency_id,
                a.agency_name,
                COALESCE((SELECT SUM(grand_total) FROM agency_bills b
                          WHERE b.agency_id = a.agency_id), 0) AS total_billed,
                COALESCE((SELECT SUM(amount) FROM agency_payments p
                          WHERE p.agency_id = a.agency_id), 0) AS total_paid
            FROM agencies a
            WHERE a.store_id = ?
            ORDER BY a.agency_name COLLATE NOCASE ASC
            """,
            (store_id,),
        ).fetchall()

    return [
        {
            "agency_id": row["agency_id"],
            "agency_name": row["agency_name"],
            "total_billed": row["total_billed"],
            "total_paid": row["total_paid"],
            "balance": row["total_billed"] - row["total_paid"],
        }
        for row in rows
    ]


def _get_bills_for_store_sqlite(store_id: int) -> list:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT bill_id, agency_id, invoice_date, grand_total, image_path, image_content_type, created_at
            FROM agency_bills WHERE store_id = ? ORDER BY bill_id DESC
            """,
            (store_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _get_payments_for_store_sqlite(store_id: int) -> list:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT payment_id, agency_id, amount, paid_on, created_at
            FROM agency_payments WHERE store_id = ? ORDER BY payment_id DESC
            """,
            (store_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _get_medicine_rows_for_store_sqlite(store_id: int) -> list:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, agency_id, product_id, name, batch_number, expiry_date
            FROM agency_medicines WHERE store_id = ? ORDER BY id DESC
            """,
            (store_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _get_bills_for_agency_sqlite(store_id: int, agency_id: int) -> list:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT bill_id, invoice_date, grand_total, image_path, image_content_type, created_at
            FROM agency_bills
            WHERE store_id = ? AND agency_id = ?
            ORDER BY bill_id DESC
            """,
            (store_id, agency_id),
        ).fetchall()
    return [dict(row) for row in rows]


def _get_payments_for_agency_sqlite(store_id: int, agency_id: int) -> list:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT payment_id, amount, paid_on, created_at
            FROM agency_payments
            WHERE store_id = ? AND agency_id = ?
            ORDER BY payment_id DESC
            """,
            (store_id, agency_id),
        ).fetchall()
    return [dict(row) for row in rows]


# =====================================================================
# Supabase implementation
#
# NOT executed/verified against a real Supabase project - written to
# follow the exact same dispatcher pattern as every other dual-backend
# repository in this codebase (modules/products, modules/sales), but
# this codebase's sandbox has no network access or `supabase` package,
# so this half could not be run here. Test it against a real Supabase
# project (with the agencies/agency_bills/agency_payments tables
# created first) before relying on it.
# =====================================================================

def _agencies_table():
    from core.supabase_client import get_supabase_client
    return get_supabase_client().table("agencies")


def _bills_table():
    from core.supabase_client import get_supabase_client
    return get_supabase_client().table("agency_bills")


def _payments_table():
    from core.supabase_client import get_supabase_client
    return get_supabase_client().table("agency_payments")


def _find_or_create_agency_supabase(store_id: int, agency_name: str) -> int:
    normalized = normalize_agency_name(agency_name)
    response = (
        _agencies_table()
        .select("agency_id")
        .eq("store_id", store_id)
        .eq("normalized_name", normalized)
        .execute()
    )
    if response.data:
        return response.data[0]["agency_id"]

    response = (
        _agencies_table()
        .insert({
            "store_id": store_id,
            "agency_name": agency_name.strip(),
            "normalized_name": normalized,
        })
        .execute()
    )
    return response.data[0]["agency_id"]


def _add_bill_supabase(
    store_id: int, agency_id: int, invoice_date: str, grand_total: float,
    image_path: str = None, image_content_type: str = None,
) -> int:
    payload = {
        "store_id": store_id,
        "agency_id": agency_id,
        "invoice_date": invoice_date or "",
        "grand_total": grand_total,
    }
    if image_path:
        payload["image_path"] = image_path
        payload["image_content_type"] = image_content_type
    response = _bills_table().insert(payload).execute()
    return response.data[0]["bill_id"]

def _medicines_table():
    from core.supabase_client import get_supabase_client
    return get_supabase_client().table("agency_medicines")


def _add_invoice_medicines_supabase(store_id: int, agency_id: int, bill_id, medicines: list) -> int:
    payload = [_medicine_payload(store_id, agency_id, bill_id, medicine) for medicine in medicines]
    try:
        _medicines_table().insert(payload).execute()
    except Exception:
        # The product_id column may not have been added to the table yet
        # (see database/agency_medicines.sql): keep the rows without it.
        without_link = [{k: v for k, v in row.items() if k != "product_id"} for row in payload]
        _medicines_table().insert(without_link).execute()
    return len(payload)


def _add_payment_supabase(store_id: int, agency_id: int, amount: float, paid_on: str = None) -> int:
    payload = {"store_id": store_id, "agency_id": agency_id, "amount": amount}
    if paid_on:
        payload["paid_on"] = paid_on
    response = _payments_table().insert(payload).execute()
    return response.data[0]["payment_id"]


def _get_agencies_with_balance_supabase(store_id: int) -> list:
    agencies = (
        _agencies_table()
        .select("agency_id, agency_name")
        .eq("store_id", store_id)
        .order("agency_name")
        .execute()
    ).data or []
    bills = (
        _bills_table().select("agency_id, grand_total").eq("store_id", store_id).execute()
    ).data or []
    payments = (
        _payments_table().select("agency_id, amount").eq("store_id", store_id).execute()
    ).data or []

    billed_by_agency = {}
    for row in bills:
        billed_by_agency[row["agency_id"]] = billed_by_agency.get(row["agency_id"], 0) + row["grand_total"]
    paid_by_agency = {}
    for row in payments:
        paid_by_agency[row["agency_id"]] = paid_by_agency.get(row["agency_id"], 0) + row["amount"]

    result = []
    for agency in agencies:
        total_billed = billed_by_agency.get(agency["agency_id"], 0)
        total_paid = paid_by_agency.get(agency["agency_id"], 0)
        result.append({
            "agency_id": agency["agency_id"],
            "agency_name": agency["agency_name"],
            "total_billed": total_billed,
            "total_paid": total_paid,
            "balance": total_billed - total_paid,
        })
    return result


_SUPABASE_PAGE = 1000


def _fetch_all(build_query) -> list:
    """All rows of a query, paged (Supabase returns at most 1000 per
    call). build_query() must return a fresh, ordered query each time."""
    rows, start = [], 0
    while True:
        batch = build_query().range(start, start + _SUPABASE_PAGE - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < _SUPABASE_PAGE:
            return rows
        start += _SUPABASE_PAGE


def _get_bills_for_store_supabase(store_id: int) -> list:
    return _fetch_all(lambda: (
        _bills_table()
        .select("bill_id, agency_id, invoice_date, grand_total, image_path, image_content_type, created_at")
        .eq("store_id", store_id).order("bill_id", desc=True)
    ))


def _get_payments_for_store_supabase(store_id: int) -> list:
    return _fetch_all(lambda: (
        _payments_table()
        .select("payment_id, agency_id, amount, paid_on, created_at")
        .eq("store_id", store_id).order("payment_id", desc=True)
    ))


def _get_medicine_rows_for_store_supabase(store_id: int) -> list:
    columns = "id, agency_id, product_id, name, batch_number, expiry_date"
    try:
        return _fetch_all(lambda: (
            _medicines_table().select(columns).eq("store_id", store_id).order("id", desc=True)
        ))
    except Exception:
        # product_id column not added yet - fall back to name matching only.
        rows = _fetch_all(lambda: (
            _medicines_table()
            .select("id, agency_id, name, batch_number, expiry_date")
            .eq("store_id", store_id).order("id", desc=True)
        ))
        for row in rows:
            row["product_id"] = None
        return rows


def _get_bills_for_agency_supabase(store_id: int, agency_id: int) -> list:
    response = (
        _bills_table()
        .select("bill_id, invoice_date, grand_total, image_path, image_content_type, created_at")
        .eq("store_id", store_id)
        .eq("agency_id", agency_id)
        .order("bill_id", desc=True)
        .execute()
    )
    return list(response.data or [])


def _get_payments_for_agency_supabase(store_id: int, agency_id: int) -> list:
    response = (
        _payments_table()
        .select("payment_id, amount, paid_on, created_at")
        .eq("store_id", store_id)
        .eq("agency_id", agency_id)
        .order("payment_id", desc=True)
        .execute()
    )
    return list(response.data or [])