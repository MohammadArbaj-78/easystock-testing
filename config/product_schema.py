"""
Canonical product field definitions.

This file exists to satisfy a core product requirement: EasyStock must
never hardcode medical-specific logic. Every layer that deals with
"what is a product" - the database schema, the OCR parser, the Product
Management forms, the Dashboard's metric calculations - reads field
definitions from here rather than each independently hardcoding column
names or labels.

For the medical-store MVP, fields are named for pharmacy inventory
(Batch Number, Expiry, MRP, GST). When EasyStock later supports grocery
or hardware stores, this file is the one place that changes - e.g.
making batch_number optional, renaming labels, or adding new field
types - without touching the database layer, OCR layer, or UI layer's
actual code.

This module defines structure and labels, not storage. The actual SQL
table definition lives in core/database.py and is informed by this file,
but kept separate because schema migrations and field metadata are
different concerns that change for different reasons.
"""

from enum import Enum


class FieldType(Enum):
    """Data type for a product field, used for validation and UI input
    widget selection (e.g. a DATE field renders a date picker, a NUMBER
    field renders a numeric input)."""
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    PERCENT = "percent"


class ProductField:
    """Definition of a single product field.

    Attributes:
        key: Internal name, used as the database column name and as the
            dict key everywhere in code. Snake_case, stable - never
            renamed once data exists, to avoid migration pain.
        label: Human-readable label shown in the UI (forms, tables,
            OCR review screens).
        field_type: The FieldType, used to pick the right validation
            rules and input widget.
        required: Whether this field must have a value before a product
            can be saved. OCR-extracted values that are required but
            came back low-confidence must be flagged for manual
            correction (per the project's OCR rules) rather than saved
            with a guessed value.
    """

    def __init__(self, key: str, label: str, field_type: FieldType, required: bool):
        self.key = key
        self.label = label
        self.field_type = field_type
        self.required = required


# The canonical field list for the current target user (medical stores).
# Order here is the order fields appear in forms and review screens.
#
# To extend EasyStock to a new business type later: do not edit this list
# in place. Instead, this becomes one of several named schemas (e.g.
# MEDICAL_STORE_FIELDS, GROCERY_STORE_FIELDS) and the active one is
# selected per-store. That refactor is deliberately deferred until a
# second business type is actually being built - building it now would
# be speculative generality with no second case to validate it against.
PRODUCT_FIELDS = [
    ProductField("name", "Medicine Name", FieldType.TEXT, required=True),
    ProductField("batch_number", "Batch Number", FieldType.TEXT, required=True),
    ProductField("expiry_date", "Expiry (MM/YY)", FieldType.DATE, required=True),
    ProductField("quantity", "Quantity", FieldType.NUMBER, required=True),
    ProductField("minimum_stock_threshold", "Minimum Stock Level", FieldType.NUMBER, required=False),
    ProductField("mrp", "MRP", FieldType.NUMBER, required=True),
    ProductField("rate", "Rate", FieldType.NUMBER, required=False),
    ProductField("gst_percent", "GST %", FieldType.PERCENT, required=False),
    ProductField("purchase_date", "Purchase Date", FieldType.DATE, required=False),
]


def get_field(key: str) -> ProductField:
    """Look up a single field definition by its key.

    Args:
        key: The field's internal name (e.g. "expiry_date").

    Returns:
        The matching ProductField.

    Raises:
        KeyError: If no field with that key exists in PRODUCT_FIELDS.
    """
    for field in PRODUCT_FIELDS:
        if field.key == key:
            return field
    raise KeyError(f"No product field defined with key '{key}'")


def get_required_field_keys() -> list:
    """Return the keys of all fields marked required.

    Used by validation logic (manual entry, OCR review) to check that
    every mandatory field has a value before a product can be saved.

    Returns:
        A list of field key strings.
    """
    return [field.key for field in PRODUCT_FIELDS if field.required]
