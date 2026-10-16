"""
Tests for the Quick Setup changes:

  1. The search box uses the same ranked, any-order search as Sales
     (names that start with what was typed first; a single-salt
     suggestion beside each combination medicine).
  2. The A-Z list shows ONLY medicines that really start with the letter
     (the old "jump to the page where the letter starts" landed on a page
     that began with the previous letter's names).
  3. Saving still SETS the quantity (unchanged), which the "start again
     from 0 after Save" display change relies on.

Uses a real, isolated SQLite file with a small master list.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class QuickSetupSearchAndLetterTests(unittest.TestCase):
    MASTER = (
        [("Accazi 250 Tablet", "X", "Acetazolamide (250mg)", None, 10),
         ("Azi 500mg Tablet", "Y", "Azithromycin (500mg)", None, 100),
         ("Azithral 500 Tablet", "Alembic", "Azithromycin (500mg)", None, 132),
         ("Azzaris 500mg Tablet", "Z", "Azithromycin (500mg)", None, 90),
         ("Ambroxol 30mg Syrup", "W", "Ambroxol (30mg)", None, 60),
         ("StayHappi Ambroxol+Guaifenesin+Terbutaline 15mg/50mg/1.25mg Syrup", "S", "Ambroxol (15mg)", "Guaifenesin (50mg)", 90),
         ("cemo 250mg Capsule", "L", "Cefixime (250mg)", None, 40)]
        # 45 medicines starting with B, so letter B needs 3 pages of 20 and the
        # old page-count jump could not land exactly on the first one
        + [(f"Bxx{i:02d} Tablet", "M", "Salt", None, 10) for i in range(45)]
        + [("Telsar H Tablet", "Z", "Telmisartan (40mg)", None, 150),
           ("Tazo 4.5 Injection", "Z", "Piperacillin (4g)", None, 300)]
    )

    def setUp(self):
        import core.database as db
        self.db = db
        self.tmp = tempfile.mkdtemp()
        self._old = (db.DATABASE_PATH, getattr(db, "DATA_DIR", None))
        db.DATABASE_PATH = os.path.join(self.tmp, "test.db")
        db.DATA_DIR = self.tmp
        db.initialize_database()
        with db.get_connection() as connection:
            connection.execute(
                "CREATE TABLE medicine_master (name TEXT, manufacturer_name TEXT, "
                "short_composition1 TEXT, short_composition2 TEXT, price REAL)"
            )
            connection.executemany("INSERT INTO medicine_master VALUES (?,?,?,?,?)", self.MASTER)
            connection.execute(
                "INSERT INTO stores (store_name, owner_name, mobile_number, password_hash) "
                "VALUES ('s', 'o', 'm', 'h')"
            )
            self.store_id = connection.execute("SELECT store_id FROM stores").fetchone()[0]

    def tearDown(self):
        self.db.DATABASE_PATH, old_dir = self._old
        if old_dir is not None:
            self.db.DATA_DIR = old_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- 1. search ----

    def test_search_puts_names_starting_with_the_typed_text_first(self):
        from modules.quick_setup import service
        names = [row["name"] for row in service.search_medicines_ranked("azi", 20)]
        self.assertEqual(names[:2], ["Azi 500mg Tablet", "Azithral 500 Tablet"])
        self.assertNotIn("Accazi 250 Tablet", names[:2])

    def test_search_accepts_a_single_character(self):
        from modules.quick_setup import service
        names = [row["name"] for row in service.search_medicines_ranked("a", 20)]
        self.assertTrue(names)
        self.assertTrue(all(name.lower().startswith("a") for name in names[:4]), names[:4])

    def test_search_finds_words_in_any_order(self):
        from modules.quick_setup import service
        names = [row["name"] for row in service.search_medicines_ranked("tab telsar", 20)]
        self.assertEqual(names[0], "Telsar H Tablet")

    def test_single_salt_suggestion_is_placed_before_its_combination(self):
        from modules.quick_setup import service
        names = [row["name"] for row in service.search_medicines_ranked("ambroxol syrup", 20)]
        combo = "StayHappi Ambroxol+Guaifenesin+Terbutaline 15mg/50mg/1.25mg Syrup"
        self.assertEqual(names.index("StayHappi Ambroxol Syrup") + 1, names.index(combo))

    def test_sales_fallback_and_quick_setup_search_rank_the_same_way(self):
        from modules.quick_setup import service as quick_setup_service
        from modules.sales import service as sales_service
        for term in ("azi", "ambroxol syrup", "telsar"):
            self.assertEqual(
                [row["name"] for row in sales_service.search_master_medicines(term)],
                [row["name"] for row in quick_setup_service.search_medicines_ranked(
                    term, sales_service.SALES_SEARCH_SUGGESTION_LIMIT, sales_service.MASTER_SEARCH_MIN_CHARACTERS)],
                term,
            )

    # ---- 2. A-Z list ----

    def test_letter_list_contains_only_names_that_start_with_the_letter(self):
        from modules.quick_setup import service
        total = service.count_medicines_starting_with("B")
        self.assertEqual(total, 45)
        seen = []
        for page in (1, 2, 3):
            rows = service.browse_medicines_starting_with_page("B", page, 20)
            self.assertTrue(all(row["name"].upper().startswith("B") for row in rows), (page, rows[:2]))
            seen += [row["name"] for row in rows]
        self.assertEqual(len(seen), 45)
        self.assertEqual(len(set(seen)), 45)                 # no repeats, none missing
        self.assertEqual(seen[0], "Bxx00 Tablet")            # the page really starts at the first B
        self.assertEqual(service.browse_medicines_starting_with_page("B", 4, 20), [])

    def test_old_page_jump_did_land_on_the_previous_letter(self):
        """Documents the bug the letter list replaces (find_page_for_letter
        is still in the code, now unused by the screen)."""
        from modules.quick_setup import service
        page = service.find_page_for_letter("B", 20)
        first_rows = service.browse_medicines_page(page, 20)
        self.assertFalse(first_rows[0]["name"].upper().startswith("B"))

    def test_letter_list_is_case_insensitive_and_safe(self):
        from modules.quick_setup import service
        self.assertEqual([r["name"] for r in service.browse_medicines_starting_with_page("c", 1, 20)], ["cemo 250mg Capsule"])
        for bad in ("", "%", "_", "AB", "1", None):
            self.assertEqual(service.count_medicines_starting_with(bad), 0, bad)
            self.assertEqual(service.browse_medicines_starting_with_page(bad, 1, 20), [], bad)

    # ---- 3. saving ----

    def test_save_still_sets_the_quantity_and_reading_it_back_gives_the_saved_value(self):
        from modules.quick_setup import service
        service.save_quantities(self.store_id, {"Azi 500mg Tablet": 7})
        self.assertEqual(service.get_saved_quantity(self.store_id, "Azi 500mg Tablet"), 7)
        service.save_quantities(self.store_id, {"Azi 500mg Tablet": 3})       # SET, not add
        self.assertEqual(service.get_saved_quantity(self.store_id, "Azi 500mg Tablet"), 3)
        service.save_quantities(self.store_id, {"Azi 500mg Tablet": 0})       # zero is never saved
        self.assertEqual(service.get_saved_quantity(self.store_id, "Azi 500mg Tablet"), 3)


class QuickSetupSessionStateTests(unittest.TestCase):
    """Quick Setup keeps the owner's work when another feature is opened.

    The functions only use session_state like a dict, so a plain dict
    stands in for it here.
    """

    def setUp(self):
        from modules.quick_setup import ui
        self.ui = ui
        self._real = ui.st.session_state
        ui.st.session_state = {}
        self.state = ui.st.session_state

    def tearDown(self):
        self.ui.st.session_state = self._real

    def test_leaving_keeps_typed_quantities_and_drops_numbers_read_from_the_database(self):
        self.state["quick_setup_cart"] = {"Typed": 3.0, "FromFile": 12.0, "JustDisplayed": 7.0}
        self.state["quick_setup_touched_names"] = {"Typed", "FromFile"}
        self.ui.discard_database_quantities()
        self.assertEqual(self.state["quick_setup_cart"], {"Typed": 3.0, "FromFile": 12.0})

    def test_leaving_with_nothing_in_the_cart_is_harmless(self):
        self.ui.discard_database_quantities()
        self.state["quick_setup_cart"] = {}
        self.ui.discard_database_quantities()
        self.assertEqual(self.state["quick_setup_cart"], {})

    def test_adjusting_a_quantity_marks_it_as_a_pending_edit(self):
        cart = {}
        self.ui._adjust_quantity(cart, "Dolo", 2)
        self.assertEqual(cart, {"Dolo": 2})
        self.assertIn("Dolo", self.state["quick_setup_touched_names"])

    def test_removing_the_file_forgets_its_list_and_its_quantities(self):
        cart = {"Dolo": 12.0, "Other": 4.0}
        self.state.update({
            "quick_setup_cart": cart,
            "quick_setup_uploaded_rows": [{"name": "Dolo", "quantity": 12.0}],
            "quick_setup_uploaded_file_name": "stock.csv",
            "quick_setup_uploaded_file_id": "stock.csv:abc",
            "quick_setup_upload_limit": 20,
            "quick_setup_touched_names": {"Dolo", "Other"},
        })
        self.ui._remove_uploaded_file()
        self.assertEqual(cart, {"Other": 4.0})
        self.assertNotIn("quick_setup_uploaded_rows", self.state)
        self.assertNotIn("quick_setup_uploaded_file_id", self.state)
        self.assertEqual(self.state["quick_setup_touched_names"], {"Other"})
        self.assertEqual(self.state["quick_setup_uploader_version"], 1)   # fresh, empty uploader

    def test_another_store_never_sees_the_previous_stores_work(self):
        self.ui._reset_if_other_store(1)
        self.state.update({
            "quick_setup_cart": {"Dolo": 5.0},
            "quick_setup_uploaded_rows": [{"name": "Dolo", "quantity": 5.0}],
            "quick_setup_search_memory": "azi",
            "unrelated_key": "keep me",
        })
        self.ui._reset_if_other_store(1)                       # same store: nothing is touched
        self.assertIn("quick_setup_uploaded_rows", self.state)
        self.ui._reset_if_other_store(2)                       # a different store logs in
        self.assertNotIn("quick_setup_cart", self.state)
        self.assertNotIn("quick_setup_uploaded_rows", self.state)
        self.assertNotIn("quick_setup_search_memory", self.state)
        self.assertEqual(self.state["unrelated_key"], "keep me")
        self.assertEqual(self.state["quick_setup_session_store"], 2)


if __name__ == "__main__":
    unittest.main()
