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


def add_bill(store_id: int, agency_id: int, invoice_date: str, grand_total: float) -> int:
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
        return _add_bill_supabase(store_id, agency_id, invoice_date, grand_total)
    return _add_bill_sqlite(store_id, agency_id, invoice_date, grand_total)


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


def _add_bill_sqlite(store_id: int, agency_id: int, invoice_date: str, grand_total: float) -> int:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO agency_bills (store_id, agency_id, invoice_date, grand_total)
            VALUES (?, ?, ?, ?)
            """,
            (store_id, agency_id, invoice_date or "", grand_total),
        )
        return cursor.lastrowid


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


def _get_bills_for_agency_sqlite(store_id: int, agency_id: int) -> list:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT bill_id, invoice_date, grand_total, created_at
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


def _add_bill_supabase(store_id: int, agency_id: int, invoice_date: str, grand_total: float) -> int:
    response = (
        _bills_table()
        .insert({
            "store_id": store_id,
            "agency_id": agency_id,
            "invoice_date": invoice_date or "",
            "grand_total": grand_total,
        })
        .execute()
    )
    return response.data[0]["bill_id"]


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


def _get_bills_for_agency_supabase(store_id: int, agency_id: int) -> list:
    response = (
        _bills_table()
        .select("bill_id, invoice_date, grand_total, created_at")
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