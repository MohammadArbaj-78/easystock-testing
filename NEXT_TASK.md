# NEXT_TASK.md

## Current Version

2.2.2 (per `VERSION` and the latest `CHANGELOG.md` entry, "Delete row bug: real root cause found and fixed (v2.2.1's fix was incomplete)").

## Current Active Task

None. The OCR Review/Edit delete-row bug (previously the active task) was root-caused and fixed in v2.2.2.

## Current Bug

None open. Resolved in v2.2.2 - see `CHANGELOG.md` and `PROJECT_MEMORY.md` Section 9 for the full root cause and fix.

## Expected Behaviour

Not applicable - no active bug is on record.

## Observed Behaviour

Not applicable - no active bug is on record.

## Files Already Investigated

None for an active task. (For reference, the v2.2.2 fix touched `modules/invoice_scan/review_service.py` and `modules/invoice_scan/review_ui.py`.)

## Files Confirmed NOT Responsible

None - no active investigation is underway.

## Current Hypothesis

None - no active bug or task to hypothesize about.

## Current Status

No active task. The delete-row bug investigation that spanned v2.2.1 and v2.2.2 is closed: root cause found (widget keys derived from list position instead of a stable per-row id), fixed (stable `_row_id` introduced), and temporary debug instrumentation removed.

## Last Investigation Point

v2.2.2 confirmed the root cause via runtime debug logging (backend index/pop() proven correct) followed by a widget-lifecycle trace, which found every widget key was built from row position rather than stable identity. Fixed and verified via simulation. No investigation has been opened since.

## Next Recommended Step

Not applicable - no active task is queued. One outstanding follow-up from v2.2.2: the fix was verified via a Streamlit-semantics-accurate simulation, not the project's real `pytest`/`AppTest` suite, because those packages could not be installed in that session's environment (no network access). Running the actual test suite in an environment with `streamlit`/`pytest` installed is recommended to fully confirm no regressions. Beyond that, the codebase's own "Pending Roadmap" items (per `PROJECT_MEMORY.md`) are the only documented candidates for future work: Super Admin authentication (`core/admin_auth.py`, referenced but not yet built), and the empty placeholder modules `modules/sales/`, `modules/billing/`, `modules/notifications/`, and `modules/super_admin/`.

## Files To Read Next

None assigned. If the test-suite verification follow-up is picked up, start with `tests/test_review_service.py` in an environment with `streamlit`/`pytest` installed. If work resumes on one of the pending roadmap items instead, the relevant starting points are:
- `core/auth.py` (for Super Admin authentication context)
- `modules/sales/__init__.py`, `modules/billing/__init__.py`, `modules/notifications/__init__.py`, `modules/super_admin/__init__.py` (all currently empty placeholders)

## Regression Risks

None identified for an active task, since none is in progress. For future awareness: the v2.2.2 fix changed the shape of every medicine dict in the Review & Edit session (added a `_row_id` key) - any new code that reads a medicine dict from that session should not assume a fixed/closed set of keys.

## Testing Required

None pending for an active task. Recommended (not blocking, not currently assigned): run the real `pytest`/`AppTest` suite for `tests/test_review_service.py` in an environment with `streamlit` installed, to confirm the v2.2.2 fix against the project's own test harness rather than only the simulation used during the fix.

## Completion Criteria

Not applicable - no active task is defined. Per project convention (`CHANGELOG.md`, `AI_RULES.md`), any new task is considered complete only when: the change is implemented, real tests are executed and pass, the full regression suite is re-run with an exact pass count reported, and a new version-bumped `CHANGELOG.md` entry is added.
