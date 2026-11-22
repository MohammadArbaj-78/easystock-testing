"""Invoice Scan first screen is one hint + one big upload; Expiry Alerts boxes allow the sidebar swipe."""
import re
import types
from unittest.mock import patch, MagicMock

from modules.invoice_scan import upload_ui
from modules.invoice_scan import review_service


class _St:
    def __init__(self, uploaded=None):
        self.session_state = {"invoice_file_uploader": uploaded} if uploaded else {}
        self.md, self.caption_calls, self.uploader_calls = [], [], []

    def subheader(self, *a, **k): pass
    def markdown(self, text, **k): self.md.append(text)
    def caption(self, text, **k): self.caption_calls.append(text)
    def info(self, *a, **k): raise AssertionError("the old format banner must be gone")
    def file_uploader(self, *a, **k):
        self.uploader_calls.append(k)
        return None
    def divider(self): pass


def _run(st):
    with patch.object(upload_ui, "st", st), patch.object(upload_ui, "get_current_store_id", return_value=1), \
         patch.object(review_service, "has_any_session", return_value=False):
        upload_ui.render_invoice_scan_page()


def test_first_screen_has_the_hint_and_a_keyed_uploader():
    st = _St()
    _run(st)
    text = "\n".join(st.md)
    assert "जितनी साफ़ और पूरे बिल की फोटो" in text and "हमेशा के लिए सेव" in text
    assert st.uploader_calls and st.uploader_calls[0]["key"] == "invoice_file_uploader"
    assert any("MB" in c for c in st.caption_calls)
    assert "st-key-invoice_file_uploader" in upload_ui._UPLOAD_CSS


def test_hint_hidden_once_a_file_is_chosen():
    st = _St(uploaded=object())
    _run(st)
    assert "जितनी साफ़ और पूरे बिल की फोटो" not in "\n".join(st.md)


def test_post_upload_pieces_untouched():
    src = open(upload_ui.__file__, encoding="utf-8").read()
    assert "फोटो पूरी तरह साफ़ नहीं है" in src           # the blur warning stays
    assert "render_review_section(uploaded_file.name, [])" in src


def test_expiry_page_boxes_are_in_the_swipe_ok_container():
    src = open("modules/alerts/ui.py", encoding="utf-8").read()
    assert 'st.container(key="swipe_ok_expiry")' in src
    app = open("app.py", encoding="utf-8").read()
    assert "st-key-swipe_ok_" in app
