"""Pure text helpers for medicine names.

Used by three places that all need the same idea of "these two names are
probably the same medicine":

  - modules/products/service.py   - matching an invoice row to a medicine
    the owner saved earlier from Sales / Quick Setup (name + quantity
    only, no batch yet).
  - modules/sales/service.py      - flexible Sales search (words in any
    order, Tab == Tablet, ...) and breaking a combination medicine into
    a single-salt suggestion.
  - tests

No database, no Streamlit, no I/O - plain functions on strings, so they
are cheap to test and cannot break anything that is already running.
"""

import re

# Spelling variants of a dosage form -> one canonical word. Only used to
# decide whether two names mean the same form (TAB == Tablet == Tabs).
_FORM_CANONICAL = {
    "tablet": "tablet", "tablets": "tablet", "tab": "tablet", "tabs": "tablet",
    "capsule": "capsule", "capsules": "capsule", "cap": "capsule", "caps": "capsule",
    "syrup": "syrup", "syrups": "syrup", "syp": "syrup", "syr": "syrup",
    "suspension": "suspension", "suspensions": "suspension", "susp": "suspension",
    "injection": "injection", "injections": "injection", "inj": "injection",
    "amp": "injection", "ampoule": "injection", "ampule": "injection",
    "cream": "cream", "gel": "gel", "lotion": "lotion",
    "ointment": "ointment", "oint": "ointment",
    "drop": "drop", "drops": "drop",
    "solution": "solution", "soln": "solution", "sol": "solution",
    "powder": "powder", "spray": "spray", "liquid": "liquid",
    "sachet": "sachet", "lozenges": "lozenges", "lozenge": "lozenges",
    "infusion": "infusion", "shampoo": "shampoo", "soap": "soap",
    "granules": "granules", "inhaler": "inhaler", "respules": "respules",
}


def clean_spaces(text) -> str:
    """Trim and collapse every run of whitespace to one space. The ONLY
    change made to a name before it is saved - no word is altered."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _tokens(text) -> list:
    """Lower-case words of a name with punctuation removed.

    "TELSAR-H" -> ["telsar", "h"];  "Allegra 120mg" -> ["allegra", "120"];
    "4 MG" -> ["4"]  (a plain mg strength is written with or without the
    unit on different invoices, so the unit "mg" is dropped; every other
    unit - mcg, g, ml, iu, % - is kept).
    """
    s = clean_spaces(text).lower()
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)         # keep decimal points only
    s = re.sub(r"[^a-z0-9.%]+", " ", s)              # punctuation -> space
    s = re.sub(r"(\d)\s+(mg|mcg|gms|gm|g|ml|iu|%)(?![a-z])", r"\1\2", s)  # "4 mg" -> "4mg"
    tokens = []
    for token in s.split():
        if re.fullmatch(r"\d+(\.\d+)?mg", token):
            token = token[:-2]
        else:
            token = re.sub(r"^(\d+(?:\.\d+)?)(?:gms|gm)$", r"\1g", token)
        tokens.append(token)
    return tokens


def normalized_name(name) -> str:
    """Strict comparison text: case, spaces and punctuation ignored, but
    no word is treated as a synonym of another. "Telsar-H Tablet" and
    "TELSAR H TABLET" are equal; "Telsar H Tab" is not."""
    return " ".join(_tokens(name))


def name_key(name) -> tuple:
    """Split a name into (core words, dosage form or None).

    The form is the LAST word that is a known dosage-form spelling, mapped
    to its canonical word; everything else - brand, strength, modifiers
    like SR / DT / Plus / Oral - stays in the core and must match exactly.
    """
    tokens = _tokens(name)
    form_index = None
    for index, token in enumerate(tokens):
        if token in _FORM_CANONICAL:
            form_index = index
    if form_index is None:
        return tuple(tokens), None
    form = _FORM_CANONICAL[tokens[form_index]]
    return tuple(tokens[:form_index] + tokens[form_index + 1:]), form


def names_match(name_a, name_b) -> bool:
    """True if two names are, in practice, the same medicine printed
    differently: same core words (so same brand AND same strength AND same
    modifiers), and the same dosage form - or the form is missing from one
    of them (invoices often print just "LEVERA 250").

    Deliberately conservative: "Provanol Plus 5" != "Provanol Plus 10",
    "Sinarest New Tablet" != "Sinarest New Nasal Spray".
    """
    core_a, form_a = name_key(name_a)
    core_b, form_b = name_key(name_b)
    if not core_a or not core_b:
        return False
    if core_a != core_b:
        return False
    return form_a == form_b or form_a is None or form_b is None


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_words(term) -> list:
    """Words to search for. Each typed word may appear anywhere in a name,
    in any order. A short form that is not simply the start of its full
    word is expanded ("syp" -> "syrup"); "tab"/"cap"/"inj" need no
    expansion because they already are the start of Tablet/Capsule/
    Injection."""
    words = []
    for token in _tokens(term):
        canonical = _FORM_CANONICAL.get(token)
        if canonical and canonical != token and not canonical.startswith(token):
            token = canonical
        words.append(token)
    return words


def match_tier(name, words):
    """How well a name matches the typed words, or None if it does not.

      0 - the name starts with what was typed
      1 - every typed word is the START of some word of the name
      2 - every typed word appears somewhere inside the name
    Lower is better; used only to order suggestions.
    """
    if not words:
        return None
    tokens = _tokens(name)
    joined = " ".join(tokens)
    query = " ".join(words)
    if joined.startswith(query):
        return 0
    if all(any(token.startswith(word) for token in tokens) for word in words):
        return 1
    if all(word in joined for word in words):
        return 2
    return None


# ---------------------------------------------------------------------------
# Combination medicines
# ---------------------------------------------------------------------------

def _parse_combination(name):
    """Recognise the generic-brand combination pattern
        <Brand> <Salt>+<Salt>[+<Salt>...] [<strengths>] <Form>
    and return {"brand", "segments", "form"}, or None if the name does not
    clearly follow it. Brand names that merely contain a plus sign -
    "Alex+ Syrup", "Briv + 50mg Tablet" - return None. If the strengths do
    not line up one-to-one with the salts, also None (a wrong guess is
    worse than no guess).
    """
    compact = clean_spaces(re.sub(r"\s*\+\s*", "+", clean_spaces(name)))
    tokens = compact.split(" ")
    if len(tokens) < 3 or "+" in tokens[0] or not tokens[0][:1].isalpha():
        return None
    brand = tokens[0]

    index = 1
    salt_tokens = []
    while (
        index < len(tokens)
        and not tokens[index][:1].isdigit()
        and tokens[index].lower() not in _FORM_CANONICAL
    ):
        salt_tokens.append(tokens[index])
        index += 1
    rest = tokens[index:]

    salts_text = " ".join(salt_tokens)
    if "+" not in salts_text:
        return None
    segments = [segment.strip() for segment in salts_text.split("+")]
    if len(segments) < 2 or any(
        not re.fullmatch(r"[A-Za-z][A-Za-z0-9 /()\-]*", segment) for segment in segments
    ):
        return None

    if rest and rest[0][:1].isdigit():
        strength, rest = rest[0], rest[1:]
        if len(strength.split("/")) != len(segments):
            return None
    if not rest or not any(token.lower() in _FORM_CANONICAL for token in rest):
        return None
    return {"brand": brand, "segments": segments, "form": " ".join(rest)}


def is_combination(name) -> bool:
    """True if the name is a generic-brand salt combination (see
    _parse_combination). Used only to list single-salt medicines first."""
    return _parse_combination(name) is not None


def split_combination(name, words) -> list:
    """Break a generic-brand combination name into a single-salt name.

    "StayHappi Ambroxol+Guaifenesin+Terbutaline 15mg/50mg/1.25mg Syrup"
    searched with the words ["ambroxol", "syrup"]
    -> [{"name": "StayHappi Ambroxol Syrup", "salt": "Ambroxol"}]

    A single is produced only when exactly ONE salt of the combination is
    what the typed words point at; typing two salts, or only the brand,
    means the person wants the combination itself, so nothing is split.
    """
    parsed = _parse_combination(name)
    if parsed is None:
        return []
    brand, segments, form = parsed["brand"], parsed["segments"], parsed["form"]

    brand_tokens = _tokens(brand)
    form_tokens = set(_tokens(form)) | set(_FORM_CANONICAL)
    salt_words = [
        word for word in words
        if word not in form_tokens
        and not any(token.startswith(word) for token in brand_tokens)
    ]
    if not salt_words:
        return []

    hit_segments = [
        segment for segment in segments
        if any(
            any(token.startswith(word) for token in _tokens(segment))
            for word in salt_words
        )
    ]
    if len(hit_segments) != 1:
        return []

    salt = hit_segments[0]
    return [{"name": f"{brand} {salt} {form}", "salt": salt}]


def is_valid_new_medicine_name(name):
    """Check a name the owner typed for a medicine found nowhere.

    Returns (True, cleaned_name) or (False, ""). Rules: 3 to 100
    characters after cleaning, and at least one letter (so "123" or "--"
    can never become a medicine).
    """
    cleaned = clean_spaces(name)
    if not 3 <= len(cleaned) <= 100:
        return False, ""
    if not re.search(r"[A-Za-z]", cleaned):
        return False, ""
    return True, cleaned