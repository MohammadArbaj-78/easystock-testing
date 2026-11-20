"""
Udhar Khata business logic (no Streamlit, no SQL).

Customers who take medicines on credit; "gave" = udhar diya, "got" = paise
mile. The balance is always worked out from the entries, never stored.
"""

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from core import name_matching
from modules.udhar import repository

KIND_GAVE = "gave"        # udhar diya: the customer owes more
KIND_GOT = "got"          # paise mile: the customer owes less
MAX_AMOUNT = 10_000_000   # one entry above one crore is almost surely a typing mistake
HISTORY_LIMIT = 300

_IST = timezone(timedelta(hours=5, minutes=30))


def today_ist() -> date:
    """Today's date in India (the server may run on another time zone)."""
    return datetime.now(_IST).date()


def normalize_mobile(text):
    """A 10 digit Indian mobile number (digits only), or None.
    "+91 98765-43210", "098765 43210" and "9876543210" are all accepted."""
    digits = re.sub(r"\D", "", str(text or ""))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return digits
    return None


def parse_amount(value):
    """A positive amount with at most 2 decimals, as a float, or None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value).replace(",", "").replace("₹", "").strip())
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount <= 0 or amount > MAX_AMOUNT:
        return None
    return float(round(amount, 2))


def get_customers(store_id: int) -> list:
    """Customers, the ones who owe the most first, then by name."""
    rows = repository.list_customers(store_id)
    return sorted(rows, key=lambda row: (-row["balance"], row["name"].lower()))


def summary(customers: list) -> dict:
    """What the top of the screen shows: the total to receive, and how many
    customers still owe something."""
    owing = [row for row in customers if row["balance"] > 0]
    return {"total": round(sum(row["balance"] for row in owing), 2), "count": len(owing)}


def add_customer(store_id: int, name: str, mobile: str) -> dict:
    """{"status": "added" | "exists" | "bad_name" | "bad_mobile", "customer_id"?, "name"?}"""
    cleaned = name_matching.clean_spaces(name)
    if not 2 <= len(cleaned) <= 60 or not re.search(r"\w", cleaned):
        return {"status": "bad_name"}
    number = normalize_mobile(mobile)
    if number is None:
        return {"status": "bad_mobile"}
    for row in repository.list_customers(store_id):
        if row["mobile"] == number:
            return {"status": "exists", "customer_id": row["customer_id"], "name": row["name"]}
    try:
        customer_id = repository.add_customer(store_id, cleaned, number)
    except Exception as error:
        text = str(error).lower()
        if "duplicate" in text or "unique" in text or "23505" in text:
            return {"status": "exists", "name": cleaned}
        raise
    return {"status": "added", "customer_id": customer_id, "name": cleaned}


def add_entry(store_id: int, customer_id: int, kind: str, amount, note="", entry_date=None) -> dict:
    """{"status": "added" | "bad_amount" | "bad_kind" | "no_customer"}"""
    if kind not in (KIND_GAVE, KIND_GOT):
        return {"status": "bad_kind"}
    value = parse_amount(amount)
    if value is None:
        return {"status": "bad_amount"}
    if repository.get_customer(store_id, customer_id) is None:
        return {"status": "no_customer"}
    when = entry_date or today_ist()
    when_text = when.isoformat() if hasattr(when, "isoformat") else str(when)
    text = name_matching.clean_spaces(note)[:200] or None
    repository.add_entry(store_id, customer_id, kind, value, text, when_text)
    return {"status": "added", "amount": value}


def get_history(store_id: int, customer_id: int, balance: float) -> list:
    """The customer's entries, newest first, each with "balance_after" (what
    the customer owed right after that entry). Worked backwards from the
    current balance, so it is right even when only the latest are shown."""
    rows = repository.list_entries(store_id, customer_id, HISTORY_LIMIT)
    running = round(float(balance), 2)
    history = []
    for row in rows:
        entry = dict(row)
        entry["balance_after"] = running
        history.append(entry)
        change = row["amount"] if row["kind"] == KIND_GAVE else -row["amount"]
        running = round(running - change, 2)
    return history


def delete_entry(store_id: int, entry_id: int) -> None:
    repository.delete_entry(store_id, entry_id)


def delete_customer_if_unused(store_id: int, customer_id: int) -> bool:
    """A customer added by mistake can be removed - only while there is no
    entry at all (a customer with a history is never deleted)."""
    if repository.list_entries(store_id, customer_id, 1):
        return False
    repository.delete_customer(store_id, customer_id)
    return True


def money(amount: float) -> str:
    """₹1,234.5 - two decimals only where they are needed."""
    text = f"{abs(amount):,.2f}".rstrip("0").rstrip(".")
    return f"₹{text}"


def reminder_message(store_name: str, customer_name: str, balance: float) -> str:
    return (
        f"Namaste {customer_name} ji, {store_name} me aapka {money(balance)} baaki hai. "
        "Kripya jald de dein. Dhanyavaad."
    )


def whatsapp_url(mobile: str, message: str) -> str:
    """A link that opens WhatsApp with the message ready for this number."""
    return f"https://wa.me/91{mobile}?text={quote(message)}"


def sms_url(mobile: str, message: str) -> str:
    """A link that opens the phone's SMS app with the message ready for this
    number ("?&body=" is the form that works on both Android and iPhone)."""
    return f"sms:+91{mobile}?&body={quote(message)}"