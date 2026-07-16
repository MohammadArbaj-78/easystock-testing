# PROJECT_STATUS.md

## Current Version

2.2.4 (per `VERSION` and the latest `CHANGELOG.md` entry).

## Project Stage

MVP. Multiple source files (`config/settings.py`, `config/product_schema.py`) explicitly label current rules and scope as "MVP" (e.g. India-only mobile validation, medical-store-only product fields, no formal migration system).

## Overall Progress

Seven modules are implemented and working: Login, Dashboard, Product Management, Invoice Upload, OCR Extraction, Review & Edit, Expiry Alerts, and Low Stock Alerts (Modules 1-7 minus Sales/Billing/Notifications/Super Admin). The application enforces multi-tenant data isolation throughout, follows a consistent layered architecture (UI → Service → Repository → Core/Config), and has an unbroken versioned release history from v1.0.0 through v2.2.4. Four modules remain unbuilt placeholder packages.

## Stable Modules

- Login (store signup/login, bcrypt password hashing)
- Dashboard (headline inventory metrics)
- Product Management (View/Search, Add, Edit, Delete)
- Invoice Upload (file validation, storage, preview)
- OCR Extraction (Gemini Vision medicine extraction)
- Review & Edit (OCR review, delete-row bug fixed in v2.2.2, mobile UI fixed in v2.2.4 after v2.2.3 was withdrawn, save to inventory)
- Expiry Alerts (15/30/60/90-day + Expired/1M/2M/3M buckets)
- Low Stock Alerts (Critical/Warning/Low severity tiers)

## Modules Under Development

None. No module currently has an open, in-progress task per `NEXT_TASK.md` or `CHANGELOG.md`.

## Placeholder Modules

- `modules/sales/` - empty package, not yet implemented
- `modules/billing/` - empty package, not yet implemented
- `modules/notifications/` (incl. `notifications/channels/`) - empty package, not yet implemented
- `modules/super_admin/` - empty package, not yet implemented (`core/admin_auth.py` referenced but also not yet built)

## Current Test Status

- **Number of tests**: 121 (per the most recent reported count in `CHANGELOG.md`, v2.2.1), across 5 test files (`test_expiry_alerts.py`, `test_low_stock_alerts.py`, `test_ocr_service.py`, `test_products_ui_threshold_checkbox.py`, `test_review_service.py`).
- **Pass status**: 121/121 passing as of the v2.2.1 release. The v2.2.2 and v2.2.4 changes were each verified via a Streamlit-semantics-accurate simulation of the real source code, not via the project's actual `pytest`/`AppTest` suite - `pytest`/`streamlit` could not be installed in that session's environment (no network access). Running the real suite is recommended before treating v2.2.2/v2.2.4 as fully verified.

## Current Known Issue

None open. The Review & Edit delete-row bug is resolved as of v2.2.2 (root cause: widget keys built from list position instead of a stable per-row id). The Review & Edit mobile UI is resolved as of v2.2.4, after v2.2.3's approach was found to produce stacked, full-width fields on real devices and was withdrawn. See `CHANGELOG.md` and `PROJECT_MEMORY.md` Section 9 for full detail, and the caveat above about test-suite verification.

## Last Stable Release

**Version**: 2.2.4

**Summary**: Replaced v2.2.3's Review & Edit mobile UI fix, which was withdrawn after real-device testing showed it produced stacked, full-width fields instead of a horizontal scroll. Rebuilt from the v2.2.2 source with all mobile CSS scoped inside a `@media (max-width: 768px)` query, forcing `flex-wrap: nowrap` (to override Streamlit's native mobile column-stacking) plus fixed per-column pixel widths (to stop columns shrinking or stretching). Desktop rendering is unaffected by construction. No backend, OCR, review-session, or save logic was touched.

## Next Planned Release

**Version**: Not documented - no next version is scheduled in the codebase or project documents.

**Main goals**: Not documented. One recommended (not committed) follow-up: run the project's actual `pytest`/`AppTest` suite against the v2.2.2/v2.2.4 fixes in an environment with `streamlit` installed. Beyond that, the only recorded candidates for future work are the placeholder modules (Sales, Billing, Notifications, Super Admin) and Super Admin authentication (`core/admin_auth.py`), per `PROJECT_MEMORY.md`'s Pending Roadmap; none has a committed version or timeline.

## Current Priority

- **High**: None documented - no open bug or in-progress task exists.
- **Medium**: Recommended follow-up (not formally prioritized) - run the real `pytest`/`AppTest` suite against the v2.2.2/v2.2.4 fixes to confirm them against the project's own test harness.
- **Low**: None documented.

## Project Health

- **Architecture**: Consistently layered (UI/Service/Repository/Core/Config) across every implemented module, with data isolation (`store_id` scoping) enforced structurally in every repository query. Dynamic widget lists follow a stable-row-id keying rule (v2.2.2). Wide mobile tables follow a media-query-scoped nowrap + fixed-column-width pattern (v2.2.4), documented in `AI_RULES.md` after the simpler `min-width`-only approach (v2.2.3) was tried and rejected.
- **Code Quality**: Shared concerns (product fields, alert colors, expiry parsing) are each centralized in one definition and reused throughout, per the codebase's own stated conventions.
- **Testing**: 121/121 tests passing as of the v2.2.1 release; the v2.2.2 and v2.2.4 fixes are verified by simulation only, pending a real `pytest` run (see Current Test Status).
- **Documentation**: `CHANGELOG.md` records every module and fix with version bumps and verification notes going back to v1.0.0, including the v2.2.3 withdrawal; `PROJECT_MEMORY.md`, `AI_RULES.md`, and `NEXT_TASK.md` have been generated from and verified against the current codebase.
- **Overall Stability**: Stable at the current MVP scope - all seven implemented modules are functionally complete with no open bug, though the v2.2.2/v2.2.4 fixes await confirmation against the real test suite, and four modules (Sales, Billing, Notifications, Super Admin) remain entirely unbuilt.

## Required Documents

- **PROJECT_MEMORY.md** - The permanent, detailed record of EasyStock's architecture, folder structure, coding/UI/business rules, completed features, fixed bugs, roadmap, and testing/development conventions.
- **AI_RULES.md** - The permanent set of engineering rules (architecture, layering, validation, testing, release conventions) that any AI working on this codebase must follow.
- **NEXT_TASK.md** - The single source of truth for whatever work is currently active (task, bug, hypothesis, investigation state); empty of content when no task is in progress.
- **CHANGELOG.md** - The chronological, versioned history of every module delivered and every bug fixed, with test-verification notes for each entry.
- **PROJECT_STATUS.md** - This one-page snapshot of EasyStock's current version, module status, test results, and overall health, meant to orient a new session in under a minute.
