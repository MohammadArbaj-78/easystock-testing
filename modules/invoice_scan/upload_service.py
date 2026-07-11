"""
Invoice upload business logic.

Owns the sequence: validate → save → return result. No Streamlit code,
no rendering, no OCR. The service layer exists so the OCR pipeline built
in the next module can call into it directly without going through the
UI, and so the upload logic is testable without a running Streamlit app.
"""

from pathlib import Path

from utils.file_utils import validate_upload, save_upload
from core.exceptions import ValidationError


def process_invoice_upload(file_obj, store_id: int) -> dict:
    """Validate and save an uploaded invoice file for a store.

    This is the ONLY entry point for saving an invoice file. Any future
    path that accepts an invoice (drag-drop, camera capture, bulk import)
    must call this function, not write to disk directly, so that
    validation and store-scoping are never accidentally bypassed.

    Args:
        file_obj: A Streamlit UploadedFile object.
        store_id: The currently logged-in store's ID. The file will be
            saved under data/uploads/{store_id}/ - never anywhere else.

    Returns:
        A dict with:
            saved_path (Path): Absolute path where the file was saved.
            filename (str): The unique filename generated for this upload.
            original_name (str): The name the user's file had before upload.
            extension (str): Lower-cased extension without the dot.

    Raises:
        ValidationError: If the file fails extension or size validation.
            The message is human-readable and suitable for st.error().
    """
    validate_upload(file_obj)
    saved_path = save_upload(file_obj, store_id)

    return {
        "saved_path": saved_path,
        "filename": saved_path.name,
        "original_name": file_obj.name,
        "extension": saved_path.suffix.lstrip(".").lower(),
    }
