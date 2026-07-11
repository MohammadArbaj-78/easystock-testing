"""
Input validation functions.

These are deliberately pure functions: given input, either return a
cleaned value or raise ValidationError. They never touch the database or
Streamlit. This keeps them trivially testable and reusable from any
layer (auth, products, sales) without dragging in unrelated dependencies.

Validate-and-clean, not just validate: each function returns the
normalized value (e.g. mobile number with spaces/symbols stripped) so
callers use one canonical form everywhere, rather than every caller
re-implementing its own cleanup before storing or comparing values.
"""

from config.settings import (
    MOBILE_NUMBER_LENGTH,
    MOBILE_NUMBER_FIRST_DIGITS,
    PASSWORD_MIN_LENGTH,
    PASSWORD_MAX_LENGTH,
)
from core.exceptions import ValidationError


def validate_mobile_number(raw_mobile_number: str) -> str:
    """Validate and normalize an Indian mobile number.

    Accepts common real-world input variations a store owner might paste
    from their contacts app (spaces, dashes, a leading +91 or 0) and
    normalizes to a plain 10-digit string. This tolerance matters for an
    MVP aimed at non-technical users - rejecting "+91 98765 43210" with a
    raw format error would be a needless onboarding friction point.

    Args:
        raw_mobile_number: User-provided mobile number, any common format.

    Returns:
        A normalized 10-digit mobile number string.

    Raises:
        ValidationError: If the cleaned number is not a valid 10-digit
            Indian mobile number.
    """
    if not raw_mobile_number or not raw_mobile_number.strip():
        raise ValidationError("Mobile number is required.")

    # Strip everything except digits, then remove a leading country code
    # (91) or trunk prefix (0) if present, so "+91-98765-43210",
    # "09876543210", and "9876543210" all normalize to the same value.
    digits_only = "".join(ch for ch in raw_mobile_number if ch.isdigit())

    if digits_only.startswith("91") and len(digits_only) == 12:
        digits_only = digits_only[2:]
    elif digits_only.startswith("0") and len(digits_only) == 11:
        digits_only = digits_only[1:]

    if len(digits_only) != MOBILE_NUMBER_LENGTH:
        raise ValidationError(
            f"Mobile number must be {MOBILE_NUMBER_LENGTH} digits."
        )

    if digits_only[0] not in MOBILE_NUMBER_FIRST_DIGITS:
        raise ValidationError("Please enter a valid mobile number.")

    return digits_only


def validate_password(password: str) -> str:
    """Validate a password against MVP rules (length only, no complexity
    requirements per product decision).

    Args:
        password: The plaintext password to validate.

    Returns:
        The password, unchanged, if valid.

    Raises:
        ValidationError: If the password length is out of range.
    """
    if not password:
        raise ValidationError("Password is required.")

    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValidationError(
            f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
        )

    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValidationError(
            f"Password must not exceed {PASSWORD_MAX_LENGTH} characters."
        )

    return password


def validate_required_text(value: str, field_label: str, max_length: int = 100) -> str:
    """Validate a required free-text field (e.g. store name, owner name).

    Args:
        value: The user-provided text.
        field_label: Human-readable field name, used in error messages
            (e.g. "Store Name").
        max_length: Maximum allowed length after stripping whitespace.

    Returns:
        The trimmed text value.

    Raises:
        ValidationError: If the value is empty or exceeds max_length.
    """
    if not value or not value.strip():
        raise ValidationError(f"{field_label} is required.")

    cleaned = value.strip()

    if len(cleaned) > max_length:
        raise ValidationError(
            f"{field_label} must not exceed {max_length} characters."
        )

    return cleaned


import re as _re


def is_valid_expiry(value: str) -> bool:
    """Validate a medicine expiry string as Month/Year format.

    This is the single canonical expiry validator for the entire project.
    Used by both review_service.py (Review & Edit) and products/service.py
    (Save). Both must accept exactly the same formats.

    Accepted: 3/28, 03/28, 12/26, 03/2028, Jun-2028, June-2028, DEC-26
    Rejected: 0/28, 13/28, 32/28, 99/9999, abc, empty string

    Args:
        value: The expiry string to validate (stripped).

    Returns:
        True if the value is a recognised Month/Year format.
    """
    value = value.strip()
    if not value:
        return False

    # Numeric MM/YY or MM/YYYY
    m = _re.match(r"^(\d{1,2})[/\-](\d{2,4})$", value)
    if m:
        month = int(m.group(1))
        year_str = m.group(2)
        year = int(year_str)
        if not (1 <= month <= 12):
            return False
        if len(year_str) == 2 and not (1 <= year <= 99):
            return False
        if len(year_str) == 4 and not (2000 <= year <= 2099):
            return False
        return True

    # Month name: Jun-2028, June-2028, DEC-26
    if _re.match(
        r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*[\s/\-]\d{2,4}$",
        value,
        _re.IGNORECASE,
    ):
        return True

    return False


# Month-name → number map used by parse_expiry_month_year
_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_expiry_month_year(value: str):
    """Parse a validated expiry string into (month, full_year) integers.

    Understands MM/YY, MM/YYYY, and Month-YYYY / Month-YY formats.
    2-digit years are interpreted as 2000+YY (e.g. 28 → 2028).

    Args:
        value: A non-empty expiry string that already passed is_valid_expiry().

    Returns:
        Tuple (month: int, year: int) with a 4-digit year.

    Raises:
        ValueError: If the string cannot be parsed (should not happen
            if is_valid_expiry() already approved it).
    """
    value = value.strip()

    # Numeric MM/YY or MM/YYYY
    m = _re.match(r"^(\d{1,2})[/\-](\d{2,4})$", value)
    if m:
        month = int(m.group(1))
        year = int(m.group(2))
        if year < 100:
            year += 2000
        return month, year

    # Month name format: Jun-2028, DEC-26, June-2028
    m2 = _re.match(
        r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*[\s/\-](\d{2,4})$",
        value,
        _re.IGNORECASE,
    )
    if m2:
        month = _MONTH_NAMES[m2.group(1).lower()[:3]]
        year = int(m2.group(2))
        if year < 100:
            year += 2000
        return month, year

    raise ValueError(f"Cannot parse expiry: {value!r}")
