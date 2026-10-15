EasyStock - Quick Setup update: which file goes where
=====================================================
Extract this ZIP into your project's main folder (the one with app.py).
Choose "Replace" / "Overwrite" when asked. Folders inside the ZIP match your project.

CHANGED files (replace the old ones):
  modules/quick_setup/ui.py          - search box, A-Z list, 0-after-Save, confirmation message
  modules/quick_setup/service.py     - shared ranked search + A-Z list functions
  modules/quick_setup/repository.py  - A-Z list queries
  modules/sales/service.py           - Sales master search now uses the shared ranked search (same behaviour)

NEW file:
  tests/test_quick_setup_search_and_letters.py   (tests - optional)

TIP: make a backup first (git commit, or copy the project folder).
