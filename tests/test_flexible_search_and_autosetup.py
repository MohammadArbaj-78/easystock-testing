"""
Tests for the Sales auto-setup work:

  1. core.name_matching        - "same medicine, printed differently"
  2. Sales flexible store search and ranked master search
     (single-salt suggestion beside each combination medicine)
  3. Saving a master / newly typed medicine from Sales
  4. Invoice save: matching a saved (name + quantity only) medicine to
     an invoice row that prints the name differently, and ADDING the
     invoice quantity to the saved quantity.

Every test that touches the database uses a real, isolated SQLite file
(same approach as the other test files: a store row is inserted directly,
bypassing core.auth).
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import name_matching
from core.exceptions import ValidationError


class NameMatchingTests(unittest.TestCase):
    def test_same_medicine_printed_differently_matches(self):
        pairs = [
            ("LEVERA 250", "Levera 250 Tablet"),
            ("TELSAR-H", "Telsar H Tablet"),
            ("RABXO DSR", "Rabxo DSR Capsule"),
            ("DEMISONE TAB", "Demisone Tablet"),
            ("TusQ DX Liquid", "TusQ-DX Liquid"),
            ("Augmentin  625 Duo Tablet", "Augmentin 625 Duo Tablet"),
            ("Augmentin 625 Duo Tab", "Augmentin 625 Duo Tablet"),
            ("LYCOJOY SYP", "Lycojoy Syrup"),
            ("Allegra 120 TAB", "Allegra 120mg Tablet"),
            ("CYPROFRESH 4 MG TAB", "Cyprofresh 4mg Tablet"),
        ]
        for a, b in pairs:
            self.assertTrue(name_matching.names_match(a, b), (a, b))

    def test_different_medicines_never_match(self):
        pairs = [
            ("PROVANOL PLUS 5", "Provanol Plus 10 Tablet"),      # strength
            ("Sinarest New Tablet", "Sinarest New Nasal Spray"),  # form
            ("Ace Tablet", "Ace Plus Tablet"),                    # modifier
            ("Telsar H Tablet", "Telsar H Syrup"),                # form
            ("Dolo 650 Tablet", "Dolo 500 Tablet"),               # strength
            ("PROVANOL PLUS 5", "Provanol Plus 5 Tablet SR"),     # SR is part of the name
            ("Telsar", "Telsar H Tablet"),                        # brand only
        ]
        for a, b in pairs:
            self.assertFalse(name_matching.names_match(a, b), (a, b))

    def test_search_words_expand_only_what_is_needed(self):
        self.assertEqual(name_matching.search_words("syp ambroxol"), ["syrup", "ambroxol"])
        self.assertEqual(name_matching.search_words("dolo 650mg"), ["dolo", "650"])
        self.assertEqual(name_matching.search_words("tamsulosin tab"), ["tamsulosin", "tab"])

    def test_split_combination_gives_single_salt_name(self):
        combo = "StayHappi Ambroxol+Guaifenesin+Terbutaline 15mg/50mg/1.25mg Syrup"
        self.assertEqual(
            name_matching.split_combination(combo, ["ambroxol", "syrup"]),
            [{"name": "StayHappi Ambroxol Syrup", "salt": "Ambroxol"}],
        )
        spaced = "DavaIndia Tamsulosin + Dutasteride 0.4mg/0.5mg Tablet"
        self.assertEqual(
            name_matching.split_combination(spaced, ["tamsulosin"])[0]["name"],
            "DavaIndia Tamsulosin Tablet",
        )

    def test_split_combination_leaves_alone_what_it_should(self):
        combo = "StayHappi Ambroxol+Guaifenesin+Terbutaline 15mg/50mg/1.25mg Syrup"
        # two salts typed, or only the brand: the person wants the combination itself
        self.assertEqual(name_matching.split_combination(combo, ["ambroxol", "guaifenesin"]), [])
        self.assertEqual(name_matching.split_combination(combo, ["stayhappi"]), [])
        # brand names that merely contain a plus sign are not combinations
        for brand_name in ["Alex+ Syrup", "Briv + 50mg Tablet", "Btric+DX Syrup Orange Sugar Free",
                           "Acton-OR Plus+ Tablet", "Azifine + 500 Tablet"]:
            self.assertFalse(name_matching.is_combination(brand_name), brand_name)
            self.assertEqual(name_matching.split_combination(brand_name, ["alex", "briv", "syrup"]), [])
        # strengths that do not line up with the salts: do not guess
        self.assertEqual(
            name_matching.split_combination("Genericart Aspirin+Atorvastatin 75mg Tablet", ["aspirin"]), []
        )

    def test_new_medicine_name_rules(self):
        self.assertEqual(name_matching.is_valid_new_medicine_name("  mupimark   cream "), (True, "mupimark cream"))
        for bad in ["ab", "123", "--- ", "x" * 101, ""]:
            self.assertEqual(name_matching.is_valid_new_medicine_name(bad), (False, ""), bad)


class _DatabaseTestCase(unittest.TestCase):
    """Real, isolated SQLite database per test, with a small master list."""

    MASTER = [
        # (name, manufacturer, composition1, composition2, price)
        ("Accazi 250 Tablet", "X", "Acetazolamide (250mg)", None, 10),
        ("Acetazide 250mg Tablet", "X", "Acetazolamide (250mg)", None, 10),
        ("Azi 500mg Tablet", "Y", "Azithromycin (500mg)", None, 100),
        ("Azithral 500 Tablet", "Alembic", "Azithromycin (500mg)", None, 132),
        ("Telsar H Tablet", "Z", "Telmisartan (40mg)", "Hydrochlorothiazide (12.5mg)", 150),
        ("Ambroxol 30mg Syrup", "W", "Ambroxol (30mg/5ml)", None, 60),
        ("StayHappi Ambroxol+Guaifenesin+Terbutaline 15mg/50mg/1.25mg Syrup", "StayHappi", "Ambroxol (15mg)", "Guaifenesin (50mg)", 90),
        ("Gemfate  Oral Suspension", "G", "Gemfibrozil (300mg)", None, 70),
    ]

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

    def add_product(self, name, quantity, batch="B1", expiry="12/2027"):
        from modules.products import repository as products_repository
        return products_repository.create_product(self.store_id, {
            "name": name, "batch_number": batch, "expiry_date": expiry, "quantity": quantity,
            "mrp": 100, "rate": 80, "gst_percent": 12, "purchase_date": "2026-10-01",
            "minimum_stock_threshold": None,
        })

    def rows(self):
        from modules.products import repository as products_repository
        return [(p["name"], p["batch_number"], p["quantity"]) for p in products_repository.get_all_products(self.store_id)]


class SalesSearchTests(_DatabaseTestCase):
    def test_store_search_unchanged_when_normal_search_finds_something(self):
        from modules.sales import service
        self.add_product("Telsar-H Tablet", 5)
        self.assertEqual(
            [p["name"] for p in service.search_store_products(self.store_id, "telsar")],
            [p["name"] for p in service.search_products(self.store_id, "telsar")],
        )

    def test_store_search_finds_words_in_any_order_when_normal_search_finds_nothing(self):
        from modules.sales import service
        self.add_product("Telsar-H Tablet", 5)
        self.assertEqual(service.search_products(self.store_id, "telsar h tab"), [])
        found = service.search_store_products(self.store_id, "telsar h tab")
        self.assertEqual([p["name"] for p in found], ["Telsar-H Tablet"])

    def test_store_search_ignores_sold_out_medicines(self):
        from modules.sales import service
        self.add_product("Telsar-H Tablet", 0)
        self.assertEqual(service.search_store_products(self.store_id, "telsar h tab"), [])

    def test_master_search_puts_names_starting_with_the_text_first(self):
        from modules.sales import service
        names = [row["name"] for row in service.search_master_medicines("azi")]
        self.assertEqual(names[:2], ["Azi 500mg Tablet", "Azithral 500 Tablet"])
        self.assertNotIn("Accazi 250 Tablet", names[:2])

    def test_master_search_needs_two_characters(self):
        from modules.sales import service
        self.assertEqual(service.search_master_medicines("a"), [])
        self.assertEqual(service.search_master_medicines(""), [])

    def test_single_salt_suggestion_sits_right_before_its_combination(self):
        from modules.sales import service
        names = [row["name"] for row in service.search_master_medicines("ambroxol syrup")]
        combo = "StayHappi Ambroxol+Guaifenesin+Terbutaline 15mg/50mg/1.25mg Syrup"
        self.assertIn(combo, names)
        self.assertIn("StayHappi Ambroxol Syrup", names)
        self.assertEqual(names.index("StayHappi Ambroxol Syrup") + 1, names.index(combo))
        # the real single-salt medicine is still listed, and ahead of the combination
        self.assertLess(names.index("Ambroxol 30mg Syrup"), names.index(combo))

    def test_extra_spaces_in_master_names_are_cleaned(self):
        from modules.sales import service
        names = [row["name"] for row in service.search_master_medicines("gemfate")]
        self.assertEqual(names, ["Gemfate Oral Suspension"])


class SaveFromSalesTests(_DatabaseTestCase):
    def test_save_master_medicine_creates_a_sellable_row(self):
        from modules.sales import service
        service.save_master_medicine(self.store_id, "Azi  500mg Tablet", 7)
        self.assertEqual(self.rows(), [("Azi 500mg Tablet", "", 7)])
        found = service.search_products(self.store_id, "azi")
        self.assertEqual(found[0]["quantity"], 7)
        service.sell_product(self.store_id, found[0]["product_id"], 3)
        self.assertEqual(service.get_sellable_stock(self.store_id, "Azi 500mg Tablet"), 4)

    def test_save_new_medicine_checks_the_typed_name(self):
        from modules.sales import service
        service.save_new_medicine(self.store_id, "  mupimark   cream ", 2)
        self.assertEqual(self.rows(), [("mupimark cream", "", 2)])
        with self.assertRaises(ValidationError):
            service.save_new_medicine(self.store_id, "12", 1)

    def test_save_rejects_bad_quantity_and_medicine_already_in_stock(self):
        from modules.sales import service
        for bad in (0, -1, 2.5, True):
            with self.assertRaises(ValidationError):
                service.save_master_medicine(self.store_id, "Azi 500mg Tablet", bad)
        self.add_product("Azi 500mg Tablet", 5)
        with self.assertRaises(ValidationError):
            service.save_master_medicine(self.store_id, "azi-500mg tablet", 3)
        self.assertEqual(len(self.rows()), 1)


class InvoiceMergeWithSavedMedicineTests(_DatabaseTestCase):
    def invoice_row(self, name, batch="B1", quantity=10, expiry="12/2027"):
        return {"name": name, "batch_number": batch, "expiry_date": expiry, "quantity": quantity,
                "mrp": "100", "rate": "80", "gst_percent": "12", "purchase_date": "2026-10-13"}

    def save_invoice(self, **kwargs):
        from modules.products import service as products_service
        return products_service.save_or_merge_invoice_lot(self.store_id, self.invoice_row(**kwargs))

    def test_invoice_quantity_is_added_to_the_saved_quantity(self):
        from modules.sales import service
        service.save_master_medicine(self.store_id, "Azithral 500 Tablet", 7)
        result = self.save_invoice(name="Azithral 500 Tablet", quantity=10)
        self.assertEqual(result["status"], "merged")
        self.assertEqual(self.rows(), [("Azithral 500 Tablet", "B1", 17)])

    def test_invoice_that_prints_the_name_differently_still_fills_the_saved_row(self):
        from modules.sales import service
        service.save_master_medicine(self.store_id, "Telsar H Tablet", 5)
        result = self.save_invoice(name="TELSAR-H", quantity=10)
        self.assertEqual(result["status"], "merged")
        self.assertEqual(self.rows(), [("TELSAR-H", "B1", 15)])

    def test_ambiguous_or_different_names_are_never_merged(self):
        from modules.sales import service
        service.save_master_medicine(self.store_id, "Telsar H Tablet", 5)
        service.save_master_medicine(self.store_id, "Telsar H Syrup", 5)
        self.assertEqual(self.save_invoice(name="TELSAR-H")["status"], "created")   # two candidates
        service.save_master_medicine(self.store_id, "Provanol Plus 10 Tablet", 4)
        self.assertEqual(self.save_invoice(name="PROVANOL PLUS 5", batch="P1")["status"], "created")  # other strength
        quantities = {name: qty for name, _batch, qty in self.rows()}
        self.assertEqual(quantities["Telsar H Tablet"], 5)
        self.assertEqual(quantities["Provanol Plus 10 Tablet"], 4)

    def test_a_real_lot_with_a_blank_batch_is_not_treated_as_a_saved_medicine(self):
        self.add_product("Levera 250 Tablet", 9, batch="", expiry="12/2027")
        result = self.save_invoice(name="LEVERA 250", batch="L1", expiry="01/2028")
        self.assertEqual(result["status"], "created")
        self.assertEqual(sorted(qty for _n, _b, qty in self.rows()), [9, 10])

    def test_existing_rules_are_unchanged(self):
        # same name + batch + expiry: quantity is added
        self.assertEqual(self.save_invoice(name="Dolo 650 Tablet", batch="D1")["status"], "created")
        self.assertEqual(self.save_invoice(name="dolo 650 tablet", batch="D1")["status"], "merged")
        self.assertEqual(self.rows(), [("Dolo 650 Tablet", "D1", 20)])
        # different batch: a separate row
        self.assertEqual(self.save_invoice(name="Dolo 650 Tablet", batch="D2")["status"], "created")
        self.assertEqual(len(self.rows()), 2)


if __name__ == "__main__":
    unittest.main()