"""What a shop's own settings do to its bills."""

import sqlite3
import unittest

import poswai_profile as profile


def food(cents, *, service_charge=True, tax_mode="included"):
    return {"cents": cents, "service_charge": service_charge, "tax_mode": tax_mode}


class SettingsStorage(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        profile.ensure_schema(self.conn)

    def test_a_shop_that_has_never_been_configured_reads_as_empty(self):
        settings = profile.read(self.conn)
        self.assertEqual(settings["tax_id"], "")
        self.assertEqual(settings["vat_rate_bp"], 0)
        self.assertEqual(settings["service_charge_bp"], 0)

    def test_only_the_settings_sent_are_changed(self):
        profile.save(self.conn, {"address": "123 หมู่ 4 เชียงดาว", "phone": "0812345678"})
        profile.save(self.conn, {"phone": "0898888888"})
        settings = profile.read(self.conn)
        self.assertEqual(settings["address"], "123 หมู่ 4 เชียงดาว")
        self.assertEqual(settings["phone"], "0898888888")

    def test_an_address_keeps_its_line_breaks(self):
        """It is printed on the receipt the way the owner typed it."""
        profile.save(self.conn, {"address": "123 ถนนช้างเผือก\nต.ศรีภูมิ อ.เมือง"})
        self.assertIn("\n", profile.read(self.conn)["address"])

    def test_the_closing_message_keeps_its_line_breaks_too(self):
        """Opening hours on one line and the LINE handle on the next is the
        whole reason a shop types two lines."""
        profile.save(self.conn, {"receipt_footer": "เปิดทุกวัน 08:00-20:00\nLINE @zzax"})
        self.assertEqual(profile.read(self.conn)["receipt_footer"].count("\n"), 1)

    def test_a_one_line_field_still_collapses_stray_spacing(self):
        profile.save(self.conn, {"legal_name": "  บริษัท   ซีแซ่บ  จำกัด "})
        self.assertEqual(profile.read(self.conn)["legal_name"], "บริษัท ซีแซ่บ จำกัด")

    def test_a_shop_opened_before_these_settings_existed_still_opens(self):
        old = sqlite3.connect(":memory:")
        self.addCleanup(old.close)
        old.execute("CREATE TABLE shop_profile (id INTEGER PRIMARY KEY CHECK (id = 1))")
        old.execute("INSERT INTO shop_profile (id) VALUES (1)")
        self.assertEqual(profile.read(old)["receipt_footer"], "")

    def test_an_unknown_setting_is_refused(self):
        with self.assertRaises(profile.ProfileError):
            profile.save(self.conn, {"owner_pin": "1234"})


class TaxIdChecks(unittest.TestCase):
    """A wrong tax number on a receipt is invisible until the year's end."""

    def test_a_real_tax_number_is_accepted(self):
        self.assertTrue(profile.valid_tax_id("0994000165510"))

    def test_a_single_digit_typo_is_caught(self):
        self.assertFalse(profile.valid_tax_id("0994000165511"))

    def test_too_few_digits_is_refused(self):
        self.assertFalse(profile.valid_tax_id("099400016551"))

    def test_dashes_and_spaces_are_stripped_before_storing(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        saved = profile.save(conn, {"tax_id": "0-9940-00165-51-0"})
        self.assertEqual(saved["tax_id"], "0994000165510")

    def test_a_shop_may_leave_the_tax_number_empty(self):
        """Most small shops are not VAT registered and have nothing to print."""
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        self.assertEqual(profile.save(conn, {"tax_id": ""})["tax_id"], "")

    def test_a_made_up_number_is_refused(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        with self.assertRaises(profile.ProfileError):
            profile.save(conn, {"tax_id": "1111111111111"})


class BillTotals(unittest.TestCase):
    PLAIN = {"vat_rate_bp": 0, "vat_inclusive": True, "service_charge_bp": 0}
    INCLUSIVE = {"vat_rate_bp": 700, "vat_inclusive": True, "service_charge_bp": 0}
    EXCLUSIVE = {"vat_rate_bp": 700, "vat_inclusive": False, "service_charge_bp": 0}
    FULL = {"vat_rate_bp": 700, "vat_inclusive": True, "service_charge_bp": 1000}

    def test_a_shop_with_no_vat_charges_exactly_the_menu_price(self):
        """Which is every shop today, so nobody's total may move."""
        result = profile.bill([food(4500), food(5000)], profile=self.PLAIN)
        self.assertEqual(result["total_cents"], 9500)
        self.assertEqual(result["vat_cents"], 0)

    def test_vat_inside_the_price_does_not_change_the_total(self):
        result = profile.bill([food(10700)], profile=self.INCLUSIVE)
        self.assertEqual(result["total_cents"], 10700)
        self.assertEqual(result["vat_cents"], 700)

    def test_vat_added_on_top_raises_the_total(self):
        result = profile.bill([food(10000)], profile=self.EXCLUSIVE)
        self.assertEqual(result["total_cents"], 10700)
        self.assertEqual(result["vat_cents"], 700)

    def test_an_exempt_item_is_left_out_of_the_tax(self):
        result = profile.bill([food(10000), food(10000, tax_mode="none")], profile=self.EXCLUSIVE)
        self.assertEqual(result["vat_cents"], 700)
        self.assertEqual(result["total_cents"], 20700)

    def test_service_charge_applies_only_to_the_lines_that_carry_it(self):
        result = profile.bill([food(10000), food(10000, service_charge=False)], profile=self.FULL)
        self.assertEqual(result["service_charge_cents"], 1000)
        self.assertEqual(result["total_cents"], 21000)

    def test_service_charge_is_taxed_like_the_food(self):
        result = profile.bill([food(10000)], profile=self.FULL)
        # 100 + 10 service, VAT inside: 110 * 7/107 = 7.20 baht
        self.assertEqual(result["total_cents"], 11000)
        self.assertEqual(result["vat_cents"], 720)

    def test_a_discount_comes_off_before_service_charge_and_tax(self):
        result = profile.bill([food(10000)], profile=self.FULL, discount_cents=2000)
        self.assertEqual(result["discount_cents"], 2000)
        self.assertEqual(result["service_charge_cents"], 800)
        self.assertEqual(result["total_cents"], 8800)

    def test_a_discount_larger_than_the_bill_only_takes_the_bill(self):
        result = profile.bill([food(5000)], profile=self.PLAIN, discount_cents=9999999)
        self.assertEqual(result["discount_cents"], 5000)
        self.assertEqual(result["total_cents"], 0)

    def test_a_discount_is_split_so_the_parts_add_back_to_the_whole(self):
        """Three lines and a discount that will not divide by three."""
        shares = profile.split_discount([1000, 1000, 1000], 100)
        self.assertEqual(sum(shares), 100)
        self.assertEqual(sorted(shares), [33, 33, 34])

    def test_the_discount_takes_its_share_from_the_lines_that_pay_service(self):
        result = profile.bill([food(10000), food(10000, service_charge=False)],
                              profile=self.FULL, discount_cents=10000)
        # Half the discount lands on the food, so service charge is on 50 baht.
        self.assertEqual(result["service_charge_cents"], 500)

    def test_a_free_bill_is_not_a_crash(self):
        result = profile.bill([food(0)], profile=self.FULL)
        self.assertEqual(result["total_cents"], 0)

    def test_a_negative_line_is_refused(self):
        with self.assertRaises(profile.ProfileError):
            profile.bill([food(-100)], profile=self.PLAIN)

    def test_the_awkward_total_stays_on_a_whole_satang(self):
        """33333 satang at 7% is where floating point drifts."""
        result = profile.bill([food(33333)], profile=self.EXCLUSIVE)
        self.assertEqual(result["total_cents"], 35666)
        self.assertEqual(result["vat_cents"], 2333)


class ChangeDue(unittest.TestCase):
    def test_the_change_is_what_is_left(self):
        self.assertEqual(profile.change_for(8500, 10000), 1500)

    def test_exact_money_leaves_no_change(self):
        self.assertEqual(profile.change_for(8500, 8500), 0)

    def test_too_little_money_is_refused(self):
        with self.assertRaises(profile.ProfileError):
            profile.change_for(8500, 8000)


if __name__ == "__main__":
    unittest.main()
