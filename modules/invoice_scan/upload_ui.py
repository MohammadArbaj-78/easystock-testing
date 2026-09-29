"""
Invoice Scan screen UI.

Combines invoice upload (Module 3a) and OCR extraction (Module 3b) in
one sequential flow:
  1. Store owner uploads an invoice image or PDF.
  2. Upload is validated, saved to their store's folder, and previewed.
  3. Gemini Vision extracts medicine line items from the same file.
  4. Results are displayed (count, time, confidence, read-only JSON).

No editing, no save button, no database writes in this screen.
The extracted data is displayed for the store owner to review visually;
saving to inventory happens in a future module.

Upload logic:    upload_service.py + utils/file_utils.py
OCR logic:       ocr_service.py
This file:       rendering only.
"""

import streamlit as st
from pathlib import Path

from modules.invoice_scan.upload_service import process_invoice_upload
from modules.invoice_scan.ocr_service import extract_medicines_from_file
from utils.file_utils import get_image_preview, get_pdf_preview, get_pdf_info
from core.session import get_current_store_id
from core.exceptions import ValidationError, OCRError, GeminiAPIError
from config.settings import UPLOADS_MAX_BYTES, ALLOWED_UPLOAD_EXTENSIONS


def render_invoice_scan_page() -> None:
    """Render the Invoice Scan page: upload area, validation feedback,
    and file preview.
    """
    st.subheader("🧾 Invoice Scan")
    st.caption(
        "Upload an invoice image or PDF. "
        "After upload, you will be able to extract medicine details."
    )

    _render_upload_section()


def _render_upload_section() -> None:
    """Render the file upload widget and handle the result."""
    store_id = get_current_store_id()

    from modules.invoice_scan import review_service

    allowed_display = ", ".join(
        f".{ext.upper()}" for ext in sorted(ALLOWED_UPLOAD_EXTENSIONS)
    )
    limit_mb = UPLOADS_MAX_BYTES // (1024 * 1024)

    st.info(
        f"📎 Supported formats: {allowed_display}  •  Maximum size: {limit_mb} MB\n\n"
        "You can also use your phone camera to capture a photo of the invoice."
    )

    # --- Photo tips (shown before upload, in simple Hindi for Indian store owners) ---
    st.markdown(
        """
        <div style='border-left: 4px solid #1A7A6E; padding: 0.6rem 1rem;
                    background: rgba(26,122,110,0.06); border-radius: 4px;
                    margin-bottom: 0.5rem;'>
            <strong>📸 फोटो साफ़ लेने के लिए</strong><br>
            • बिल पूरा दिखाई दे।<br>
            • कैमरा सीधा रखें।<br>
            • रोशनी अच्छी हो।<br>
            • फोटो धुंधली न हो।<br>
            • Batch Number और Expiry साफ़ दिखें।
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Final stabilization fix: once a review session is active, the
    # uploader's own "browse/replace" control must not stay usable -
    # previously it did, so picking a second file (even by mistake)
    # would silently start reset_session_for_new_upload() and discard
    # whatever was being reviewed. Disabling the widget while a session
    # exists is the smallest possible fix: it doesn't add a new control
    # or change the upload component's structure, and it doesn't touch
    # SHA-256 cache/reset logic below at all - re-enabling happens
    # naturally, with no extra code, the moment has_any_session()
    # becomes False again (i.e. after "Clear Review").
    session_already_active = review_service.has_any_session()

    uploaded_file = st.file_uploader(
        "Choose an invoice file or take a photo",
        type=["jpg", "jpeg", "png", "pdf"],
        label_visibility="collapsed",
        key="invoice_file_uploader",
        disabled=session_already_active,
    )

    # --- Navigation persistence: show cached review when file_uploader is None ---
    # st.file_uploader returns None when the user navigates away and returns.
    # If a review session exists we render it from cache so the store owner
    # never loses their edits just because they checked the Dashboard.
    if uploaded_file is None:
        if review_service.has_any_session():
            st.divider()
            _render_ocr_section(uploaded_file=None)
        else:
            _render_empty_state()
        return

    # --- Compute SHA-256 fingerprint of the uploaded bytes ---
    # Using the file hash (not the filename) as the session identity key
    # means two files named "invoice.jpg" with different content always
    # start a fresh OCR session, while re-uploading the identical file
    # correctly reuses the cached session without re-running Gemini.
    file_bytes = uploaded_file.getvalue()
    file_hash = review_service.compute_file_hash(file_bytes)

    try:
        result = process_invoice_upload(uploaded_file, store_id)
    except ValidationError as error:
        # Stabilization fix: the file itself was rejected (wrong type,
        # too large, etc.) BEFORE we ever touch the review session. The
        # store owner's current valid review, if any, for a different
        # file must be left exactly as it was - the reset below only
        # ever runs once we know this is a real, accepted upload, so a
        # single invalid/mistaken upload attempt can no longer wipe a
        # perfectly good in-progress review.
        st.error(str(error))
        _render_empty_state()
        return

    # The upload itself is valid. Only now do we check whether it's a
    # different invoice from whatever session (if any) is currently
    # active, and if so, destroy that previous session completely
    # before this new upload's extraction begins - automatically, with
    # no "Clear Review" click required. Uses reset_session_for_new_upload()
    # rather than clear_session(): the latter also resets the
    # file_uploader's own widget key, which must not happen here since
    # that widget has already been instantiated with this new file
    # earlier in this same script run (see
    # review_service.reset_session_for_new_upload's docstring). An
    # identical re-upload of the same file (hash unchanged) still
    # correctly reuses the cached session below - the SHA-256 cache
    # logic itself is untouched.
    if not review_service.is_review_session_active(file_hash):
        review_service.reset_session_for_new_upload()

    _render_success_and_preview(uploaded_file, file_hash, result)


def _render_empty_state() -> None:
    """Show placeholder content when no file has been uploaded yet."""
    st.markdown(
        """
        <div style='text-align:center; padding:2.5rem 1rem; color:#888;
                    border:2px dashed #ccc; border-radius:8px;
                    margin-top:0.5rem;'>
            📄 No invoice uploaded yet.<br>
            <small>Upload a file above to see a preview.</small>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_success_and_preview(uploaded_file, file_hash: str, result: dict) -> None:
    """Show a success banner, file preview, and OCR extraction results.

    Args:
        uploaded_file: The original Streamlit UploadedFile.
        file_hash:     SHA-256 hex digest of the uploaded file bytes.
        result: The dict returned by process_invoice_upload().
    """
    st.success(
        f"✅ '{result['original_name']}' uploaded successfully and saved securely."
    )

    st.divider()
    st.markdown("**Preview**")

    ext = result["extension"]

    if ext == "pdf":
        _render_pdf_preview(uploaded_file)
    else:
        _render_image_preview(uploaded_file)

    # Show the save path so technically-minded store owners (or the
    # developer during testing) can confirm isolation is working.
    with st.expander("File details"):
        st.text(f"Saved as:  {result['filename']}")
        st.text(f"Location:  {result['saved_path']}")
        st.text(f"Original:  {result['original_name']}")

    # Quality check for images only (PDFs are rasterized by PyMuPDF at a
    # fixed DPI so resolution/brightness checks on the rendered image would
    # not reflect the original scan quality — skip them for PDFs).
    if result["extension"] != "pdf":
        _render_image_quality_warning(uploaded_file)

    st.divider()
    _render_ocr_section(uploaded_file, file_hash)


def _render_ocr_section(uploaded_file, file_hash: str = None) -> None:
    """Render OCR extraction results and the Review & Edit table.

    Gemini is called AT MOST ONCE per unique file (identified by SHA-256
    hash). On every subsequent rerun, and also when the user navigates
    away and returns (uploaded_file becomes None), the cached session is
    rendered instantly with no API calls.

    Args:
        uploaded_file: The Streamlit UploadedFile, or None when called
                       from the navigation-persistence path.
        file_hash:     SHA-256 hex digest. None only on the nav-back path,
                       where we render purely from cached session state.
    """
    from modules.invoice_scan import review_service
    from modules.invoice_scan.review_ui import render_review_section

    st.markdown("**🔍 Medicine Extraction**")

    # --- Navigation-persistence path (uploaded_file is None) ---
    # User returned from another page; file_uploader is None but session
    # is still live. Render everything from cache.
    if uploaded_file is None:
        _render_cached_session(review_service, render_review_section, source_filename="")
        return

    # --- Session hit: same file hash, skip Gemini ---
    if review_service.is_review_session_active(file_hash):
        _render_cached_session(
            review_service, render_review_section, source_filename=uploaded_file.name
        )
        return

    # --- First render for this file: call Gemini ---
    with st.spinner("Extracting medicines ......."):
        try:
            ocr_result = extract_medicines_from_file(uploaded_file)
        except GeminiAPIError as exc:
            st.error(f"⚠️ API Error: {exc}")
            # The uploaded file is still held by the file_uploader widget
            # (no review session was created, so it was never disabled or
            # cleared) - clicking this button simply reruns the script,
            # which retries extraction on that SAME file. No re-upload
            # needed.
            st.button("🔄 Try Again", key="invoice_retry_after_gemini_error")
            return
        except OCRError as exc:
            st.error(f"⚠️ Extraction Error: {exc}")
            st.button("🔄 Try Again", key="invoice_retry_after_ocr_error")
            return

    medicines = ocr_result["medicines"]
    count = ocr_result["medicine_count"]
    elapsed = ocr_result["extraction_time_seconds"]

    if count == 0:
        st.warning(
            "No medicines were found in this invoice. "
            "This can happen if the image is blurry, the invoice is a summary "
            "page, or this is not a medicine invoice. "
            "Please check the preview above and try a clearer scan."
        )
        return

    # Store in session — all future reruns (edits, deletes, adds, nav) skip Gemini.
    review_service.initialise_review_session(
        file_hash=file_hash,
        source_filename=uploaded_file.name,
        medicines=medicines,
        ocr_metadata={
            "medicine_count": count,
            "extraction_time_seconds": elapsed,
            "model": ocr_result.get("model", ""),
        },
    )

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Medicines Found", count)
    with col2:
        st.metric("Extraction Time", f"{elapsed}s")

    st.caption(
        "ℹ️ Review the extracted data below. "
        "Gemini Vision reads the invoice image — accuracy depends on scan "
        "quality. Always verify quantities and expiry dates before saving."
    )

    render_review_section(uploaded_file.name, [])


def _render_cached_session(review_service, render_review_section, source_filename: str) -> None:
    """Render metrics and review table from cached session state.

    Shared by the session-hit path and the navigation-persistence path.
    """
    meta = review_service.get_ocr_metadata()
    count = len(review_service.get_medicines())

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Medicines Found", count)
    with col2:
        elapsed = meta.get("extraction_time_seconds", "—")
        st.metric(
            "Extraction Time",
            f"{elapsed}s" if isinstance(elapsed, float) else str(elapsed),
        )

    st.caption(
        "ℹ️ Review the extracted data below. "
        "Gemini Vision reads the invoice image — accuracy depends on scan "
        "quality. Always verify quantities and expiry dates before saving."
    )

    # Use the stored filename when called from the nav-persistence path
    # (where source_filename is ""), so the review table can identify
    # its session correctly.
    cached_filename = source_filename or review_service.get_session_filename()
    render_review_section(cached_filename, [])


def _render_image_preview(uploaded_file) -> None:
    """Display an image file preview.

    Args:
        uploaded_file: A Streamlit UploadedFile (JPG/PNG/JPEG).
    """
    try:
        img = get_image_preview(uploaded_file)
        st.image(img, width="stretch")
    except ValidationError as error:
        st.warning(
            f"⚠️ File was saved successfully but preview is unavailable: {error}"
        )


def _render_pdf_preview(uploaded_file) -> None:
    """Display a PDF preview: rasterized first page if possible, or
    metadata if rasterization fails (e.g. encrypted PDF).

    Args:
        uploaded_file: A Streamlit UploadedFile (.pdf).
    """
    preview_image = get_pdf_preview(uploaded_file)

    if preview_image is not None:
        st.image(preview_image, caption="Page 1 of PDF", width="stretch")
    else:
        # Graceful fallback - still show the store owner something
        # useful even if we can't rasterize (encrypted PDF, corrupt
        # file, etc.).
        info = get_pdf_info(uploaded_file)
        st.markdown(
            f"""
            <div style='border-left: 4px solid #1976D2; padding: 0.8rem 1rem;
                        border-radius:4px; background:rgba(0,0,0,0.02);'>
                📄 <strong>{info['filename']}</strong><br>
                Pages: {info['page_count'] or 'Unknown'} &nbsp;•&nbsp;
                Size: {info['file_size_mb']} MB
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption(
            "Visual preview is not available for this PDF "
            "(it may be encrypted or in a non-standard format). "
            "The file has been saved successfully."
        )


def _render_image_quality_warning(uploaded_file) -> None:
    """Run a lightweight image quality check and show a Hindi warning if
    the image looks too blurry, too dark, too bright, or too small for
    reliable OCR. Never blocks the upload — this is a warning only.

    Method (PIL only, no AI, no extra dependencies):
      1. Blur:        Apply PIL FIND_EDGES kernel and compute variance of
                      the edge response. Very low variance → blurry image.
                      Threshold: edge_variance < 500.
                      Calibrated against real invoice images:
                        Sharp invoice   → ~4000–6000
                        Gaussian-blurred → ~270 (correctly flagged)
                        Solid uniform   → ~270 (correctly flagged)
      2. Brightness:  Mean grayscale pixel value (0–255).
                      < 40  → too dark to read.
                      > 253 → truly overexposed (all-white, no visible text).
                      Normal white-paper invoices score 230–242, so a
                      ceiling of 253 avoids false positives on white paper.
      3. Resolution:  Width × height in total pixels.
                      < 80 000 px → too small for reliable OCR
                      (equivalent to ~283×283 px).

    PDFs are excluded by the caller — they are rasterized by PyMuPDF at a
    fixed DPI, so quality checks on the rasterized image would not reflect
    the original scan quality.

    Args:
        uploaded_file: The Streamlit UploadedFile (JPG/JPEG/PNG).
    """
    try:
        from PIL import Image, ImageFilter
        import io

        data = uploaded_file.getvalue()
        img = Image.open(io.BytesIO(data)).convert("L")  # grayscale

        width, height = img.size
        total_pixels = width * height

        # --- Resolution check ---
        resolution_ok = total_pixels >= 80_000

        # --- Brightness check ---
        # tobytes() returns raw pixel bytes — each byte is one grayscale px.
        raw = img.tobytes()
        pixel_count = len(raw)
        mean_brightness = sum(raw) / pixel_count
        # < 40: too dark. > 253: completely washed out (all white, no text).
        # Normal white-paper invoices sit at ~230-242, so 253 avoids false
        # positives on legitimate invoices shot under good lighting.
        brightness_ok = 40 <= mean_brightness <= 253

        # --- Blur check (variance of edge-detection response) ---
        edges = img.filter(ImageFilter.FIND_EDGES)
        ep = edges.tobytes()
        ep_count = len(ep)
        edge_mean = sum(ep) / ep_count
        edge_sq_mean = sum(x * x for x in ep) / ep_count
        edge_variance = edge_sq_mean - edge_mean ** 2
        # Calibrated thresholds (measured on synthetic invoice images):
        #   Sharp invoice: ~4000-6000  ✓ pass
        #   Blurred scan:  ~270        ✗ fail (correctly flagged)
        blur_ok = edge_variance >= 500

        quality_ok = resolution_ok and brightness_ok and blur_ok

    except Exception:
        # If the check itself fails (unusual image format, memory error,
        # etc.) do not show a warning — silently proceed. The check is
        # informational; its failure must never block OCR.
        return

    if quality_ok:
        return

    st.warning(
        "⚠️ फोटो पूरी तरह साफ़ नहीं है।\n\n"
        "बेहतर रिज़ल्ट के लिए फोटो दोबारा लें।\n\n"
        "Batch Number और Expiry गलत आ सकते हैं।"
    )
