# PROJECT_STATUS.md

## Current Version

2.4.7 (per `VERSION` and the latest `CHANGELOG.md` entry).

## Project Stage

MVP. Multiple source files (`config/settings.py`, `config/product_schema.py`) explicitly label current rules and scope as "MVP" (e.g. India-only mobile validation, medical-store-only product fields, no formal migration system).

## Overall Progress

Eight modules are implemented and working: Login, Dashboard, Product Management, Invoice Upload, OCR Extraction, Review & Edit, Expiry Alerts, Low Stock Alerts, and Sales. Sales' search experience was reworked in v2.4.1, a real `StreamlitAPIException` crash was found and fixed in v2.4.2, v2.4.3 added a search clear button and compact quantity selector, v2.4.4 added general mobile layout polish to the Sales page, and v2.4.5 fixed Sales History's time display. v2.4.6 strengthened the Gemini OCR extraction prompt (accuracy/anti-hallucination rules, prompt-text-only - no schema, API-call-count, or parsing changes). v2.4.7 added mobile-only sidebar polish app-wide (bigger touch targets, larger nav text, auto-close on navigation) - the project's first and only use of JavaScript, added under firm guardrails and gated to mobile only. The application enforces multi-tenant data isolation throughout, follows a consistent layered architecture (UI → Service → Repository → Core/Config), and has an unbroken versioned release history from v1.0.0 through v2.4.7. Three modules remain unbuilt placeholder packages.

## Stable Modules

- Login (store signup/login, bcrypt password hashing)
- Dashboard (headline inventory metrics)
- Product Management (View/Search, Add, Edit, Delete)
- Invoice Upload (file validation, storage, preview)
- OCR Extraction (Gemini Vision medicine extraction; extraction prompt strengthened in v2.4.6)
- Review & Edit (OCR review, delete-row bug fixed in v2.2.2, mobile UI fixed in v2.2.4 after v2.2.3 was withdrawn, save to inventory)
- Expiry Alerts (15/30/60/90-day + Expired/1M/2M/3M buckets)
- Low Stock Alerts (Critical/Warning/Low severity tiers)
- Sales (autocomplete search with stock filter and Frequently Sold since v2.4.1; a `StreamlitAPIException` fixed and suggestion rows made compact in v2.4.2; search clear button and always-compact quantity selector in v2.4.3; general mobile layout polish in v2.4.4; local-time display fixed in v2.4.5; search, stepper, sell, and permanent append-only history complete since v2.4.0)

Sidebar navigation (`app.py`, all modules) now also has mobile-only touch-target/font polish and an auto-close-on-navigate behavior as of v2.4.7.

## Modules Under Development

None. Sales is complete; v2.4.1 through v2.4.5 improved its search/selling UX, mobile layout, and time display without leaving it in a partial state. v2.4.6 and v2.4.7 were cross-cutting polish (OCR prompt; app-wide sidebar) rather than module work.

## Placeholder Modules

- `modules/billing/` - empty package, not yet implemented
- `modules/notifications/` (incl. `notifications/channels/`) - empty package, not yet implemented
- `modules/super_admin/` - empty package, not yet implemented (`core/admin_auth.py` referenced but also not yet built)

## Current Test Status

- **Number of tests**: 121 (per the most recent reported count in `CHANGELOG.md`, v2.2.1), across 5 test files. No new file has been added to the project's own `pytest` suite for Sales, OCR, or the sidebar work - every release since has instead been verified by direct execution/simulation, since `pytest`/`streamlit`/`google.genai` remain unavailable in this working environment (no network access).
- **Pass status**: 121/121 passing as of the v2.2.1 release. Since then: Sales Phase 1/2 (v2.3.0-v2.3.1, no Streamlit dependency) - 26 checks via real SQLite execution. Sales UI work (v2.4.0-v2.4.5) - verified via a Streamlit-semantics-accurate simulation shim executing the real, unmodified source end-to-end (corrected in v2.4.2 after it missed a real bug, then sanity-checked against the old broken code). A separate 6-check suite confirms Dashboard/Low Stock automatically reflect a sale with zero code changes to either module. v2.4.6 (OCR prompt) - verified by importing the real `ocr_service.py` module directly (`google.genai` mocked) and confirming the JSON schema, API call site, and response parsing are all unchanged - 8 checks. v2.4.7 (sidebar) - the actual, unmodified injected JavaScript was extracted, syntax-checked with Node.js, and exercised against a mocked DOM in Node - 9 checks confirming correct mobile-only gating, no false-triggers, and graceful degradation. 101 checks passed in the v2.4.7 regression sweep (0 failures); across all work since v2.2.1, well over 150 checks have passed with 0 unresolved failures. Running the real `pytest`/`AppTest` suite, and manual testing on a real desktop browser and mobile device, both remain recommended before the demo.

## Current Known Issue

None open. The Sales `StreamlitAPIException` on selecting a search suggestion is resolved as of v2.4.2. The Review & Edit delete-row bug is resolved as of v2.2.2, and its mobile UI is resolved as of v2.2.4. The v2.4.7 sidebar auto-close JavaScript depends on Streamlit's current internal DOM structure (not a public API) and is written to degrade gracefully (navigation keeps working, sidebar just won't auto-close) if a future Streamlit version changes that structure - flagged as a known limitation, not an open bug. See `CHANGELOG.md` and `PROJECT_MEMORY.md` Section 9 for full detail, and the caveat above about test-suite verification.

## Last Stable Release

**Version**: 2.4.7

**Summary**: Mobile-only sidebar polish, `app.py` only. Bigger touch targets and ~12% larger nav text (media-query-gated CSS, scoped to the sidebar's `role="radiogroup"`). A small `streamlit.components.v1.html` component - the project's first and only JavaScript - auto-closes the sidebar after a nav tap on mobile, tracked via `sessionStorage` so it never fires on first load, gated to the same 768px breakpoint as the CSS, and written to fail silently if Streamlit's internal collapse-button DOM structure ever changes. `NAV_PAGES` (labels, icons, dispatch) and the routing dispatch are confirmed byte-unchanged. No business logic, Dashboard, Sales, Invoice Scan, OCR, Gemini prompt, or database changes.

## Next Planned Release

**Version**: Not formally committed.

**Main goals**: Not documented as a committed plan. The only recorded candidates for future work are the remaining placeholder modules (Billing, Notifications, Super Admin) and Super Admin authentication (`core/admin_auth.py`), per `PROJECT_MEMORY.md`'s Pending Roadmap; none of those has a committed version or timeline. A recurring, still-open recommendation across recent releases: run the project's actual `pytest`/`AppTest` suite, and manually verify the v2.4.7 sidebar behavior on a real desktop browser and mobile device before the demo (v2.2.2 through v2.4.7 were all verified by simulation or direct execution instead, for lack of network access to install `streamlit`/`pytest`/`google.genai` in this working environment).

## Current Priority

- **High**: Manual verification of v2.4.7's sidebar behavior (auto-close, touch targets, fonts) on a real desktop browser and mobile device ahead of the demo - this was verified by code inspection and a mocked-DOM JS test, not a live browser.
- **Medium**: Recommended follow-up (not formally prioritized) - run the real `pytest`/`AppTest` suite against v2.2.2 through v2.4.7 to confirm them against the project's own test harness.
- **Low**: None documented.

## Project Health

- **Architecture**: Consistently layered (UI/Service/Repository/Core/Config) across every implemented module, with data isolation (`store_id` scoping) enforced structurally in every repository query. v2.4.3/v2.4.4 both reused the scoped-CSS pattern already established for the Review & Edit table (unconditional and media-query-gated variants respectively). v2.4.5's timestamp-display pattern (store UTC, convert only at display time, never hardcode an offset) and v2.4.7's JavaScript-usage guardrails (fail-silent, best-effort DOM selectors, prefer web standards over Streamlit-internals, viewport-gated) are both now documented in `AI_RULES.md`.
- **Code Quality**: Shared concerns (product fields, alert colors, expiry parsing) are each centralized in one definition and reused throughout. Sales continues to reuse `products_repository` (via its own service) rather than duplicating product-table access, and reuses existing UI patterns rather than introducing new ones. `app.py`'s new sidebar helpers are the project's first JavaScript, scoped narrowly under the new `AI_RULES.md` guardrails rather than opening the door to JS more broadly.
- **Testing**: 121/121 tests passing as of the v2.2.1 release; v2.2.2/v2.2.4/v2.4.0-v2.4.5/v2.4.7 (Streamlit UI/JS changes) verified by simulation, v2.3.0/v2.3.1 (no Streamlit dependency) and v2.4.6 (OCR prompt, mocked `google.genai`) verified by direct execution - all pending a real `pytest` run (see Current Test Status).
- **Documentation**: `CHANGELOG.md` records every module and fix with version bumps and verification notes going back to v1.0.0; `PROJECT_MEMORY.md`, `AI_RULES.md`, and `NEXT_TASK.md` have been generated from and verified against the current codebase.
- **Overall Stability**: Stable at the current MVP scope - all eight implemented modules are functionally complete with no open bug. Three modules (Billing, Notifications, Super Admin) remain entirely unbuilt.

## Required Documents

- **PROJECT_MEMORY.md** - The permanent, detailed record of EasyStock's architecture, folder structure, coding/UI/business rules, completed features, fixed bugs, roadmap, and testing/development conventions.
- **AI_RULES.md** - The permanent set of engineering rules (architecture, layering, validation, testing, release conventions) that any AI working on this codebase must follow.
- **NEXT_TASK.md** - The single source of truth for whatever work is currently active (task, bug, hypothesis, investigation state); empty of content when no task is in progress.
- **CHANGELOG.md** - The chronological, versioned history of every module delivered and every bug fixed, with test-verification notes for each entry.
- **PROJECT_STATUS.md** - This one-page snapshot of EasyStock's current version, module status, test results, and overall health, meant to orient a new session in under a minute.
