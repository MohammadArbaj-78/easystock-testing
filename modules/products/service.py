"""
Product Management business logic.

Owns validation and orchestration for creating, editing, and deleting
products - the rules for what makes a product's data valid, separate
from how it's stored (repository.py) or displayed (ui.py).

Validation here is driven by config/product_schema.py rather than
hardcoding "name is required" style checks per field, so a future change
to which fields are required for a different business type changes one
config file, not this service.
"""

from datetime import date, datetime

from modules.products import repository as products_repository
from config.product_schema import PRODUCT_FIELDS, FieldType
from core.exceptions import ValidationError


def _validate_and_clean_product_data(form_data: dict, enforce_future_expiry: bool) -> dict:
    """Validate raw form input against product_schema rules and return
    a cleaned dict ready for the repository.

    Iterates config.product_schema.PRODUCT_FIELDS rather than checking
    each field by name, so adding, removing, or changing a field's
    required/type status in product_schema.py automatically changes
    what this function enforces - no parallel validation logic to keep
    in sync.

    Args:
        form_data: Raw values keyed by product_schema field keys, as
            collected from the UI form.
        enforce_future_expiry: If True, rejects an expiry date in the
            past. True for new products (catches a typo'd date before
            it enters the system), False for edits to an existing
            product (a product can legitimately already be expired -
            that's exactly what the Expired Products metric is for, and
            a store owner must still be able to open and re-save/correct
            an expired product's other fields without being blocked by
            its own expiry date).

    Returns:
        A cleaned dict with the same keys, with type coercion applied
        (e.g. quantity/mrp as numbers, dates as ISO strings) and
        whitespace trimmed from text fields.

    Raises:
        ValidationError: If a required field is missing, or any field's
            value fails its type-specific validation rule.
    """
    cleaned = {}

    # minimum_stock_threshold is validated separately, before the
    # generic field loop, because its rule depends on a UI-only signal
    # (was the "custom threshold" checkbox on?) that has no equivalent
    # in product_schema.py - it's not a property of the field itself,
    # it's a property of how this specific form chose to expose it.
    # Handling it here keeps that rule visible and testable in one
    # place, rather than smuggled into the generic NUMBER branch below
    # as a special case for one field key.
    custom_threshold_enabled = form_data.get("_minimum_stock_threshold_enabled", False)

    if custom_threshold_enabled:
        raw_threshold = form_data.get("minimum_stock_threshold")
        if raw_threshold is None or (isinstance(raw_threshold, str) and not raw_threshold.strip()):
            raise ValidationError("Please enter a custom minimum stock level.")
        try:
            threshold_value = int(float(raw_threshold))
        except (TypeError, ValueError):
            raise ValidationError("Please enter a custom minimum stock level.")
        if threshold_value < 1:
            raise ValidationError("Minimum stock must be at least 1.")
        cleaned["minimum_stock_threshold"] = threshold_value
    else:
        # Checkbox off (or this call came from a non-UI caller that
        # never set the sentinel, e.g. a future OCR pipeline) means
        # "use the store-wide default" - stored as NULL, exactly as
        # before this fix.
        cleaned["minimum_stock_threshold"] = None

    for field in PRODUCT_FIELDS:
        if field.key == "minimum_stock_threshold":
            continue  # already handled above

        raw_value = form_data.get(field.key)

        is_empty = raw_value is None or (
            isinstance(raw_value, str) and not raw_value.strip()
        )

        if is_empty:
            if field.required:
                raise ValidationError(f"{field.label} is required.")
            cleaned[field.key] = None
            continue

        if field.field_type == FieldType.TEXT:
            cleaned[field.key] = str(raw_value).strip()

        elif field.field_type == FieldType.DATE:
            # expiry_date stores Month/Year strings (e.g. "03/28", "Jun-2028")
            # from both manual entry (Product Management) and OCR-sourced saves.
            # Other DATE fields (purchase_date) remain ISO-format.
            if field.key == "expiry_date":
                from utils.validators import is_valid_expiry
                str_value = str(raw_value).strip() if not isinstance(raw_value, date) else raw_value.isoformat()
                if not is_valid_expiry(str_value) and not isinstance(raw_value, date):
                    raise ValidationError(
                        "Expiry must be in Month/Year format "
                        "(e.g. 3/28, 03/28, 03/2028 or Jun-2028)."
                    )
                # Store as-is for Month/Year strings; ISO for date objects
                cleaned[field.key] = raw_value.isoformat() if isinstance(raw_value, date) else str_value
            else:
                # Streamlit's date_input returns a datetime.date object
                # directly; this also accepts an ISO string for callers
                # outside the UI.
                if isinstance(raw_value, date):
                    cleaned[field.key] = raw_value.isoformat()
                else:
                    try:
                        cleaned[field.key] = date.fromisoformat(str(raw_value)).isoformat()
                    except ValueError:
                        raise ValidationError(f"{field.label} is not a valid date.")

        elif field.field_type in (FieldType.NUMBER, FieldType.PERCENT):
            try:
                numeric_value = float(raw_value)
            except (TypeError, ValueError):
                raise ValidationError(f"{field.label} must be a number.")

            if numeric_value < 0:
                raise ValidationError(f"{field.label} cannot be negative.")

            if field.field_type == FieldType.PERCENT and numeric_value > 100:
                raise ValidationError(f"{field.label} cannot exceed 100%.")

            # Quantity is stored as whole units (you can't have half a
            # tablet strip in this MVP's model); monetary/percent fields
            # keep decimal precision.
            if field.key == "quantity":
                cleaned[field.key] = int(numeric_value)
            else:
                cleaned[field.key] = numeric_value

    # Future-expiry check: only for add_product (enforce_future_expiry=True).
    # Uses parse_expiry_month_year so both ISO dates (from the date picker,
    # which become real date objects converted to ISO above) and MM/YY strings
    # are handled by the same canonical path.
    if enforce_future_expiry and cleaned.get("expiry_date"):
        from utils.validators import parse_expiry_month_year
        expiry_str = cleaned["expiry_date"]
        try:
            exp_month, exp_year = parse_expiry_month_year(expiry_str)
            today = date.today()
            if (exp_year, exp_month) < (today.year, today.month):
                raise ValidationError(
                    "Expiry must be in the current month or a future month. "
                    f"'{expiry_str}' appears to be in the past."
                )
        except ValueError:
            # parse_expiry_month_year could not parse this value; the format
            # check above already validated it, so just skip the future check.
            pass

    return cleaned


def add_product(store_id: int, form_data: dict) -> int:
    """Validate and create a new product for a store.

    Args:
        store_id: The currently logged-in store's ID.
        form_data: Raw field values from the Add Product form.

    Returns:
        The newly created product_id.

    Raises:
        ValidationError: If validation fails, or if a product with the
            same name and batch number already exists for this store
            (the same medicine batch should be edited/restocked, not
            duplicated as a second row).
    """
    cleaned_data = _validate_and_clean_product_data(form_data, enforce_future_expiry=True)

    existing = products_repository.get_all_products(store_id, search_term=cleaned_data["name"])
    for product in existing:
        if (
            product["name"].lower() == cleaned_data["name"].lower()
            and product["batch_number"].lower() == cleaned_data["batch_number"].lower()
        ):
            raise ValidationError(
                f"A product named '{cleaned_data['name']}' with batch "
                f"number '{cleaned_data['batch_number']}' already exists. "
                "Please edit the existing entry instead, or use a "
                "different batch number."
            )

    return products_repository.create_product(store_id, cleaned_data)


def edit_product(store_id: int, product_id: int, form_data: dict) -> None:
    """Validate and update an existing product.

    Past expiry dates are allowed here (unlike add_product) since a
    product already in the system may have genuinely expired - that's
    the normal, expected lifecycle this app tracks, not an input error.

    Args:
        store_id: The currently logged-in store's ID.
        product_id: The product being edited.
        form_data: Raw field values from the Edit Product form.

    Raises:
        ValidationError: If validation fails, or if the product does not
            belong to this store (propagated from the repository).
    """
    cleaned_data = _validate_and_clean_product_data(form_data, enforce_future_expiry=False)
    products_repository.update_product(store_id, product_id, cleaned_data)


def remove_product(store_id: int, product_id: int) -> None:
    """Delete a product.

    Args:
        store_id: The currently logged-in store's ID.
        product_id: The product to delete.

    Raises:
        ValidationError: If the product does not belong to this store
            (propagated from the repository).
    """
    products_repository.delete_product(store_id, product_id)


def search_products(store_id: int, search_term: str = None) -> list:
    """List all products for a store, optionally filtered by search term.

    Args:
        store_id: The currently logged-in store's ID.
        search_term: Optional text to filter by name or batch number.

    Returns:
        A list of product dicts.
    """
    return products_repository.get_all_products(store_id, search_term)


def get_product(store_id: int, product_id: int) -> dict:
    """Get a single product by ID for editing.

    Args:
        store_id: The currently logged-in store's ID.
        product_id: The product to fetch.

    Returns:
        The product dict.

    Raises:
        ValidationError: If no product with this ID exists for this
            store.
    """
    product = products_repository.get_product_by_id(store_id, product_id)
    if product is None:
        raise ValidationError("Product not found.")
    return product
