"""
Regression test for the Phase 9.1 preprocessing fix.

Phase 9 found a real defect: a photographed invoice
(IMG20260616160324.jpg, 3072x4096) was perspective-warped down to an
unusable 86x786 sliver, because geometry._find_largest_quadrilateral()
accepted a small/spurious 4-point contour (measured at 0.52% of the
frame) as the document boundary with no plausibility check against the
image's actual size.

This file is intentionally small and narrowly targeted at that one
proven defect - it is not a general preprocessing test suite.
"""

import os

import pytest


class TestQuadrilateralAreaGuard:
    def test_min_area_ratio_constant_exists_and_is_reasonable(self):
        from modules.invoice_scan.preprocess import geometry
        assert hasattr(geometry, "_MIN_QUADRILATERAL_AREA_RATIO")
        ratio = geometry._MIN_QUADRILATERAL_AREA_RATIO
        # Must comfortably exceed the proven-bad case's measured 0.52%,
        # while staying well under 1.0 (a legitimate document photo is
        # rarely the *entire* frame edge-to-edge).
        assert 0.05 < ratio < 0.9

    def test_spurious_small_quadrilateral_is_rejected(self):
        # Directly exercises the guard with a synthetic gray image and a
        # small quadrilateral contour, without depending on any real
        # invoice photo being present in this environment.
        import numpy as np
        import cv2
        from modules.invoice_scan.preprocess import geometry

        gray = np.zeros((1000, 1000), dtype=np.uint8)
        # A small white square (~1% of the frame) with a black border,
        # so Canny finds a clean small quadrilateral - the same shape of
        # failure as the proven real-image defect (a tiny 4-point
        # contour unrelated to the actual document).
        cv2.rectangle(gray, (50, 50), (150, 150), 255, thickness=-1)
        cv2.rectangle(gray, (48, 48), (152, 152), 0, thickness=2)

        quad = geometry._find_largest_quadrilateral(gray)
        assert quad is None, (
            "A small spurious quadrilateral (~1% of frame) must be "
            "rejected, not trusted as the document boundary"
        )

    def test_legitimate_large_quadrilateral_is_still_accepted(self):
        # The guard must not break real, legitimate perspective
        # correction - a quadrilateral covering most of the frame must
        # still be found and accepted.
        import numpy as np
        import cv2
        from modules.invoice_scan.preprocess import geometry

        gray = np.zeros((1000, 1000), dtype=np.uint8)
        cv2.rectangle(gray, (50, 50), (950, 950), 255, thickness=-1)
        cv2.rectangle(gray, (48, 48), (952, 952), 0, thickness=2)

        quad = geometry._find_largest_quadrilateral(gray)
        assert quad is not None, (
            "A legitimate large document quadrilateral (~81% of frame) "
            "must still be accepted"
        )


class TestRealInvoiceImages:
    """Uses the two real invoice photos from Phase 9, if present on disk
    in this environment. Skips (does not fail/fabricate) if the fixture
    files are not available - these are real photos provided by the
    project owner during testing, not files that ship with the repo."""

    _IMG_DIR = "/mnt/user-data/uploads"
    _FAILING_IMAGE = "IMG20260616160324.jpg"
    _WORKING_IMAGE = "IMG20260728170635.jpg"

    def _load(self, name):
        path = os.path.join(self._IMG_DIR, name)
        if not os.path.exists(path):
            pytest.skip(f"Real invoice fixture not present in this environment: {path}")
        from PIL import Image
        return Image.open(path)

    def test_previously_failing_invoice_no_longer_produces_a_sliver(self):
        from modules.invoice_scan.preprocess.pipeline import preprocess_image

        img = self._load(self._FAILING_IMAGE)
        original_size = img.size
        result = preprocess_image(img)

        assert result.success
        width, height = result.processed_image.size
        # The proven-bad output was 86x786. Assert we are nowhere near
        # that degenerate scale, and specifically not that exact result.
        assert (width, height) != (86, 786)
        assert width >= original_size[0] * 0.5
        assert height >= original_size[1] * 0.5

    def test_previously_working_invoice_is_unaffected(self):
        from modules.invoice_scan.preprocess.pipeline import preprocess_image

        img = self._load(self._WORKING_IMAGE)
        original_size = img.size
        result = preprocess_image(img)

        assert result.success
        assert result.processed_image.size == original_size
        assert result.quality_report.perspective_level is None
