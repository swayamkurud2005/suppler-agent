import unittest

from app.schemas.schemas import ContractPricingDetails
from app.services.numeric_parsing import parse_numeric_price
from app.services.price_normalization_service import price_normalization_service
from app.services.webpage_extraction_service import webpage_extraction_service


class MarketPriceParsingTests(unittest.TestCase):
    def test_parse_numeric_price(self):
        for value, expected in [
            (1250, 1250.0), ("", None), ("   ", None), (None, None),
            ("₹ 1,25,000.50", 125000.5), ("$1,250.75", 1250.75),
            ("not listed", None), ("1,000-1,200", None), (0, 0.0),
        ]:
            with self.subTest(value=value):
                self.assertEqual(parse_numeric_price(value), expected)

    def test_heuristic_extraction_skips_text_without_verifiable_price(self):
        contract = ContractPricingDetails(material_name="Copper Cathode", contract_unit_price=100.0, currency="INR", unit_of_measurement="kg")
        record = webpage_extraction_service._heuristic_extract("Premium Grade A copper cathode available now", contract)
        self.assertIsNone(record["price"])
        self.assertIsNone(record["currency"])
        self.assertIsNone(record["unit"])

    def test_heuristic_extraction_parses_valid_market_price(self):
        contract = ContractPricingDetails(material_name="Copper Cathode", contract_unit_price=100.0, currency="INR", unit_of_measurement="kg")
        record = webpage_extraction_service._heuristic_extract("Wholesale quote: INR 1,250 per kg", contract)
        self.assertEqual(record["price"], 1250.0)
        self.assertEqual(record["currency"], "INR")
        self.assertEqual(record["unit"], "kg")

    def test_normalization_rejects_unknown_currency_and_incompatible_unit(self):
        contract = ContractPricingDetails(material_name="Copper Cathode", contract_unit_price=100.0, currency="INR", unit_of_measurement="kg")
        self.assertIsNone(price_normalization_service.normalize(100, "ABC", "kg", contract)[0])
        self.assertIsNone(price_normalization_service.normalize(100, "INR", "container", contract)[0])

    def test_normalization_converts_tonne_to_kg(self):
        contract = ContractPricingDetails(material_name="Copper Cathode", contract_unit_price=100.0, currency="INR", unit_of_measurement="kg")
        normalized, _, ratio, _ = price_normalization_service.normalize(100000, "INR", "tonne", contract)
        self.assertEqual(normalized, 100.0)
        self.assertEqual(ratio, 0.001)
