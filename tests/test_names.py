import unittest
from decimal import Decimal

from scrapers.names import parse_pumpkin_name


class NameParsingTests(unittest.TestCase):
    def test_standard_name_and_status(self):
        result = parse_pumpkin_name("2020 Paton 2023 DMG", reference_year=2025)
        self.assertEqual((result.weight_lbs, result.grower, result.year, result.flags),
                         (Decimal("2020"), "Paton", 2023, ("DMG",)))

    def test_missing_and_short_year(self):
        self.assertIsNone(parse_pumpkin_name("2083 Bledsoe", reference_year=2025).year)
        short = parse_pumpkin_name("1442 Leuenberger 24", reference_year=2025)
        self.assertEqual(short.year, 2024)
        self.assertTrue(short.year_inferred)

    def test_cross_types_and_invalid_weight(self):
        self.assertEqual(parse_pumpkin_name("Self").kind, "self")
        self.assertEqual(parse_pumpkin_name("Open").kind, "open")
        self.assertEqual(parse_pumpkin_name("-5 Bad 2024").kind, "invalid")


if __name__ == "__main__":
    unittest.main()
