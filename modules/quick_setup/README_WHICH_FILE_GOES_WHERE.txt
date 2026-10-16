EasyStock - Quick Setup: keep upload list + search/letter after changing feature
===============================================================================
Extract into your project's main folder (the one with app.py) and choose "Replace".

CHANGED files:
  app.py                                           - ONE small block near the end (what happens when you leave Quick Setup)
  modules/quick_setup/ui.py                        - upload list stays until "File hatao"; search text + A-Z letter remembered
  tests/test_quick_setup_search_and_letters.py     - tests (5 new ones added)

TIP: make a backup first (git commit, or copy the project folder).
