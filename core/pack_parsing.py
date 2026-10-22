"""Turn the text of an invoice's PACK column into ONE number: how many
countable pieces (tablets, capsules, ampoules, sachets) one unit of the
quantity contains.

Pure text in, number out - no database, no Streamlit, no Gemini - so the
number is worked out by fixed rules, never guessed by an AI model.

What real distributor invoices print, and what this returns:

    "10 Tablets", "30 Table...", "15 Capsu...", "7 Capsul..."  -> 10, 30, 15, 7
    "10's", "10S"                                              -> 10
    "1*10", "1*15", "1 x 15"   (1 strip of N)                  -> 10, 15
    "10*2ML", "10*2 gm"        (N ampoules / sachets of a size) -> 10
    "60 ml", "100 gm", "5GM", "50Gms", "200 ML"  (one bottle,
        tube or tin is one piece)                              -> 1
    anything else - "10*10", "1 Strip", "Pack", "", unreadable -> None
        (None = unknown; the owner fills it in on the Review screen)

Leaving it unknown is deliberate: a wrong guess would silently corrupt
the strip / tablet arithmetic later, an empty cell only asks for a number.
"""

import re

# Largest believable "pieces per unit"; anything bigger is a misread.
_MAX_PACK = 5000

# A weight / volume unit written right after a number: "60 ml", "5GM", "50Gms".
_UNIT = r"(?:ml|l|ltr|gm|gms|g|gram|grams|kg|mg|mcg|iu)"


def pack_number(text):
    """The pack number for an invoice PACK cell, or None if it cannot be
    worked out safely.

    Args:
        text: The PACK cell exactly as printed (may be cut off, e.g.
            "30 Table...", or empty).

    Returns:
        A positive float (10.0, 15.0, 1.0 ...) or None.
    """
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    cleaned = cleaned.replace("\u00d7", "*")                 # the multiplication sign
    if not cleaned:
        return None

    # "10*2ml" / "10 x 2 gm": the FIRST number counts the pieces, the second
    # is just each piece's size. Checked before "1*10" so that "10*2ml" is
    # not mistaken for a strip.
    match = re.fullmatch(rf"(\d+)\s*[*x]\s*\d+(?:\.\d+)?\s*{_UNIT}", cleaned)
    if match:
        return _valid(match.group(1))

    # "1*10", "1 x 15": one strip of N. "10*10" or "2*10" is ambiguous
    # (boxes of strips?) and is left unknown.
    match = re.fullmatch(r"(\d+)\s*[*x]\s*(\d+)", cleaned)
    if match:
        return _valid(match.group(2)) if int(match.group(1)) == 1 else None

    # "10 tablets", "30 table...", "15 capsu...", "10 tabs", "10 caps".
    match = re.match(r"(\d+)\s*(?:tab|cap)", cleaned)
    if match:
        return _valid(match.group(1))

    # "10's", "10s", "10 s"
    match = re.fullmatch(r"(\d+)\s*'?\s*s", cleaned)
    if match:
        return _valid(match.group(1))

    # Only a weight or volume: one bottle / tube / tin = one piece.
    if re.fullmatch(rf"\d+(?:\.\d+)?\s*{_UNIT}", cleaned):
        return 1.0

    return None


def _valid(digits: str):
    number = float(digits)
    return number if 0 < number <= _MAX_PACK else None


def format_pack(number) -> str:
    """How the number is shown in the Review table: "15", not "15.0";
    "" when unknown."""
    if number is None:
        return ""
    return str(int(number)) if float(number) == int(number) else str(number)