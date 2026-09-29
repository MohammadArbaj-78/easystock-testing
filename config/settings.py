"""
Application-wide settings and constants.

Centralizing these values here means tuning the app (DB location, password
rules, alert thresholds) never requires touching business logic - only
this file. This is the same principle behind product_schema.py: behavior
that might reasonably change should live in config, not be embedded in
the code that uses it.
"""

import os

from dotenv import load_dotenv

# Load .env as the very first thing this module does, before any
# os.environ.get() call below. config.settings is the earliest-imported
# module in the whole app (app.py's first import is
# `from config.settings import APP_NAME`), and every environment-derived
# constant in this file - including DEBUG_PREPROCESSING - is computed
# once, at import time. Loading .env anywhere later than this (e.g. only
# inside ocr_service.py, as before) means those constants get permanently
# fixed from a still-empty environment before .env is ever read. This is
# the one and only load_dotenv() call in the project - it must not be
# duplicated elsewhere. No-op if a value is already set in the real
# environment (e.g. Streamlit Cloud secrets), matching load_dotenv()'s
# own default behavior of not overriding existing environment variables.
load_dotenv()

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
UPLOADS_MAX_BYTES = 25 * 1024 * 1024  # 25 MB

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
GEMINI_MODEL = "gemini-3.5-flash"

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

# Requirement 2 (Supabase session persistence): the browser localStorage
# key used to persist the Supabase refresh token across a full browser
# close/reopen - st.session_state itself cannot survive that (it is
# per-WebSocket-connection, gone the instant the browser reconnects).
# Shared by core/login_ui.py (writes it after a successful login/
# signup) and app.py (reads it on a fresh connection with no active
# session, and clears it on logout) so both sides agree on one name.
LOCALSTORAGE_REFRESH_TOKEN_KEY = "easystock_refresh_token"

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

# --- OCR Preprocessing / Image Quality Analysis (OCR Architecture v1.0) ---
# Score -> level boundaries used only by preprocess/quality.py (Layer B
# analysis) to classify a raw measurement into one of QUALITY_RULES.md's
# human-readable categories (e.g. a blur variance of 40 -> BlurLevel.POOR).
# These are analysis-time classification boundaries, not Rule Engine
# decision thresholds - the Rule Engine (not yet implemented) reads the
# *levels* these produce, not raw scores or these boundaries directly.
# Centralised here, per the architecture's own "no hardcoded thresholds"
# principle, so calibrating any of these later never requires touching
# quality.py itself.

# Blur: variance of the Laplacian of the grayscale image. Lower variance
# means fewer sharp edges, i.e. a blurrier image. Each constant is the
# maximum score still classified at that level; anything at or above
# BLUR_VARIANCE_GOOD_MAX is BlurLevel.EXCELLENT. The Good/Excellent
# boundary (500) matches the single blur threshold already calibrated
# against real invoices for the existing v1.7.0 upload-time quality
# warning (modules/invoice_scan/upload_ui.py) - reused here as a
# known-good reference point, not re-derived from scratch.
BLUR_VARIANCE_CRITICAL_MAX = 50
BLUR_VARIANCE_POOR_MAX = 100
BLUR_VARIANCE_ACCEPTABLE_MAX = 250
BLUR_VARIANCE_GOOD_MAX = 500

# Brightness: mean grayscale pixel value, 0 (black) - 255 (white).
BRIGHTNESS_VERY_DARK_MAX = 40
BRIGHTNESS_DARK_MAX = 80
BRIGHTNESS_BRIGHT_MIN = 200
BRIGHTNESS_OVEREXPOSED_MIN = 240

# Contrast: standard deviation of grayscale pixel values.
CONTRAST_LOW_MAX = 35
CONTRAST_HIGH_MIN = 80

# Noise: estimated sigma via a Laplacian-based noise estimator. Not a
# perceptual 0-100 scale - a raw estimator output on the same scale as
# grayscale pixel values.
NOISE_LOW_MAX = 3.0
NOISE_MEDIUM_MAX = 8.0

# Rotation: estimated tilt in degrees from perfectly upright (0deg).
ROTATION_STRAIGHT_MAX_DEGREES = 1.0
ROTATION_SLIGHT_MAX_DEGREES = 5.0
ROTATION_MODERATE_MAX_DEGREES = 15.0

# Perspective: an invoice's detected quadrilateral outline is flagged as
# perspective-distorted once any of its four corner angles deviates from
# a true 90 degrees by more than this many degrees.
PERSPECTIVE_ANGLE_DEVIATION_THRESHOLD_DEGREES = 10.0

# Resolution: minimum pixel dimensions still considered adequate for
# reading fine print (batch numbers, expiry dates); the "high" boundary is
# the width above which resolution is comfortably more than adequate.
RESOLUTION_MIN_WIDTH_PX = 800
RESOLUTION_MIN_HEIGHT_PX = 600
RESOLUTION_HIGH_WIDTH_PX = 2000

# Shadow: uneven-lighting detection via a grid of blocks across the image;
# the score is the difference (in mean grayscale brightness) between the
# brightest and darkest block. GRID_SIZE=4 -> a 4x4 grid of blocks.
SHADOW_GRID_SIZE = 4
SHADOW_PARTIAL_RANGE_MIN = 40
SHADOW_SIGNIFICANT_RANGE_MIN = 80

# Invoice Detection: heuristic based on the area (as a fraction of the
# whole frame) covered by the largest detected contour - a real invoice
# photographed reasonably close-up should dominate the frame.
INVOICE_MIN_CONTOUR_AREA_RATIO = 0.3
INVOICE_UNCERTAIN_CONTOUR_AREA_RATIO = 0.1

# --- Enhancement (Layer A, OCR Architecture v1.0 Phase 5) ---
# Fixed corrective strengths used by preprocess/enhance.py. These are NOT
# classification thresholds (unlike the Phase 2 constants above) - they
# are the magnitude applied uniformly every time a given step fires, since
# RuleDecision carries no per-image measurement for Enhancement to scale
# its correction by (Enhancement consumes only Image + RuleDecision, per
# OCR Architecture v1.0 Phase 5).

# Brightness/Contrast: percent of the histogram clipped from each end
# before stretching the remainder to fill the full range (PIL
# ImageOps.autocontrast's `cutoff`). Self-corrects both under- and
# over-exposed images and low contrast alike, without needing to know
# which direction a given image's problem runs in.
BRIGHTNESS_CONTRAST_AUTOCONTRAST_CUTOFF = 1

# Noise Removal: PIL ImageFilter.MedianFilter kernel size (must be odd).
# A small, fixed kernel favours preserving fine print (batch numbers,
# expiry dates) over aggressive denoising.
NOISE_REMOVAL_MEDIAN_FILTER_SIZE = 3

# Sharpening: PIL ImageEnhance.Sharpness factor (1.0 = unchanged; greater
# than 1.0 sharpens). Kept modest to avoid introducing artifacts.
SHARPEN_ENHANCEMENT_FACTOR = 2.0

# --- App metadata ---
APP_NAME = "EasyStock"

# --- Preprocessing Debug Instrumentation (OCR Architecture v1.0, Phase 8.5) ---
# Observation-only. Fails safe: any value other than exactly "true"
# (case-insensitive, whitespace-trimmed) resolves to False, so an unset,
# misspelled, or blank environment variable can never accidentally turn
# debug capture on - the deployed application behaves exactly as before
# this phase unless this variable is deliberately set to "true". When
# False (the default), nothing in modules/invoice_scan/preprocess/pipeline.py's
# debug hooks executes, and no debug/ folder or file is ever created.
DEBUG_PREPROCESSING = (
    os.environ.get("DEBUG_PREPROCESSING", "false").strip().lower() == "true"
)
print("[TEMP-INSTRUMENT] config/settings.py: DEBUG_PREPROCESSING =", DEBUG_PREPROCESSING)  # TEMPORARY

# Base folder debug sessions are written under (one subfolder per run,
# named invoice_<timestamp>). Relative to the project root when running
# via Streamlit's normal working directory.
DEBUG_OUTPUT_DIR = "debug"
