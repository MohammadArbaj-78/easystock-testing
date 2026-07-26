"""
Application-wide settings and constants.

Centralizing these values here means tuning the app (DB location, password
rules, alert thresholds) never requires touching business logic - only
this file. This is the same principle behind product_schema.py: behavior
that might reasonably change should live in config, not be embedded in
the code that uses it.
"""

import os

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DATABASE_PATH = os.path.join(DATA_DIR, "easystock.db")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")

# --- Authentication rules (MVP) ---
# Mobile number is the login identity for the MVP. India-only validation
# for now: 10 digits, first digit 6-9. Revisit if EasyStock expands beyond
# India or adds country-code support.
MOBILE_NUMBER_LENGTH = 10
MOBILE_NUMBER_FIRST_DIGITS = ("6", "7", "8", "9")

PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 20

# --- Upload / Invoice Scan ---
# Maximum size for any uploaded invoice file. Checked in utils/file_utils.py
# before the file is written to disk - never trust st.file_uploader's
# maximal size alone since that's a client hint, not a server guarantee.
UPLOADS_MAX_BYTES = 10 * 1024 * 1024  # 10 MB

# Extensions accepted for invoice upload. Lower-case, without the leading
# dot. Checked against the uploaded filename before any file I/O. Centralised
# here so adding a new accepted type (e.g. "tiff") never requires touching
# the UI file.
ALLOWED_UPLOAD_EXTENSIONS = {"jpg", "jpeg", "png", "pdf"}

# PDF preview resolution. 150 DPI gives a clear, readable thumbnail without
# producing an image so large it slows the browser down. Increase to 200 if
# store owners report difficulty reading the preview.
PDF_PREVIEW_DPI = 150

# --- Inventory thresholds ---
# Used when a product has no per-product minimum_stock_threshold set
# (NULL in the database). A store can override this per product in
# Product Management (Module 5); this is just the fallback so Dashboard
# and Alerts have a sensible default from day one without forcing every
# store to configure every product before the app is useful.
DEFAULT_LOW_STOCK_THRESHOLD = 2

# "Expiring soon" on the Dashboard uses this window. The dedicated
# Expiry Alerts module (Module 6) offers the full 7/15/30 day
# breakdown below; the Dashboard shows one summary number using the
# widest window so nothing expiring within a month is missed at a glance.
DASHBOARD_EXPIRY_SOON_DAYS = 30

# Expiry Alerts module windows, in ascending order of urgency-window
# size. A product is bucketed into exactly one of these (its single
# most urgent applicable window) rather than appearing in every window
# it technically qualifies for - see modules/alerts/service.py for the
# bucketing logic. Defined as a list (not separate constants) so the
# alerts service can iterate it in order without hardcoding "7, then
# 15, then 30" as a literal sequence in business logic.
EXPIRY_ALERT_WINDOWS_DAYS = [15, 30, 60, 90]

# --- Sales ---
# Sales History (Module: Sales) shows only the most recent sales, newest
# first, with no pagination for the MVP. This caps how many rows
# get_sales_history() ever returns, so the query and the page stay fast
# regardless of how many sales a store accumulates over time. Tunable
# here, not hardcoded in modules/sales/repository.py's SQL.
SALES_HISTORY_DISPLAY_LIMIT = 100

# Sales search behaves as a lightweight autocomplete, not a full list -
# capped so the suggestion list never renders hundreds of results.
SALES_SEARCH_SUGGESTION_LIMIT = 10

# "Frequently Sold" (shown when the search box is empty) surfaces this
# many top-selling, currently-in-stock medicines.
SALES_FREQUENTLY_SOLD_LIMIT = 8

# sales_history has no live stock column, so the service layer must
# fetch more top-sold product_ids than it needs and filter out any that
# are now out of stock (or deleted) to find SALES_FREQUENTLY_SOLD_LIMIT
# in-stock results. This bounds that candidate fetch.
SALES_FREQUENTLY_SOLD_CANDIDATE_LIMIT = 50

# --- OCR / Gemini ---
# Model name to use for invoice extraction. Gemini 1.5 Flash is chosen
# for the MVP: it supports vision input, is fast enough for interactive
# use (typically 2-5 seconds per invoice), and is cost-effective for the
# call volume expected from 5-10 test stores. Swap to "gemini-1.5-pro"
# here (not in ocr_service.py) if higher accuracy is needed later.
GEMINI_MODEL = "gemini-2.5-flash"

# Request timeout in seconds. Gemini vision calls on a typical invoice
# image complete in 2-5 s; 30 s gives comfortable headroom for slow
# connections without blocking the UI indefinitely. Surfaced here so it
# can be tuned without touching service code.
GEMINI_TIMEOUT_SECONDS = 30

# --- Session ---
# Streamlit session_state key under which the active session dict is
# stored. Defined once here so core/session.py is the only file that
# needs to reference session_state directly.
SESSION_STATE_KEY = "easystock_session"

# --- Database backend selection (SQLite -> Supabase migration, Phase 3) ---
# The single, one-place switch for which backend a dual-backend
# repository (currently only modules/products/repository.py, see its
# Phase 2 dual-backend implementations) actually uses. Read once, here,
# from the ACTIVE_DB_BACKEND environment variable - not from Streamlit
# secrets, so this file (and anything that imports only this constant)
# stays importable without the `streamlit` package installed.
#
# Fails safe: any value other than exactly "supabase" (case-insensitive,
# whitespace-trimmed) resolves to "sqlite", so an unset, misspelled, or
# blank environment variable can never accidentally activate the
# Supabase path - the deployed application keeps behaving exactly as it
# does today unless this variable is deliberately set to "supabase".
# No other file defines or re-derives this value; a dual-backend
# repository imports ACTIVE_DB_BACKEND from here rather than defining
# its own backend constant - see AI_RULES.md's "Multi-Backend
# Repository Rules."
ACTIVE_DB_BACKEND = (
    "supabase"
    if os.environ.get("ACTIVE_DB_BACKEND", "sqlite").strip().lower() == "supabase"
    else "sqlite"
)

# --- App metadata ---
APP_NAME = "EasyStock"
