import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_trading import _build_metadata_alerts
from utils.okx_utils import OKXMetadataError, calc_contract_size, get_instrument_map


class OkxUtilsTest(unittest.TestCase):
    @patch("utils.okx_utils.okx_get_instruments")
    def test_get_instrument_map_skips_missing_required_metadata(self, mock_get_instruments):
        mock_get_instruments.return_value = [
            {"instId": "ETH-USDT-SWAP", "ctVal": "0.01", "ctMult": "", "lotSz": "1"},
            {"instId": "SOL-USDT-SWAP", "ctVal": "", "ctMult": "1", "lotSz": "1"},
            {"instId": "TRX-USDT-SWAP", "ctVal": "1", "ctMult": "1", "lotSz": ""},
        ]

        instrument_map, skipped = get_instrument_map()

        self.assertIn("ETH-USDT-SWAP", instrument_map)
        self.assertEqual(instrument_map["ETH-USDT-SWAP"]["ctMult"], 1.0)
        self.assertEqual(skipped["SOL-USDT-SWAP"], "missing ctVal")
        self.assertEqual(skipped["TRX-USDT-SWAP"], "missing lotSz")

    def test_calc_contract_size_raises_when_metadata_missing(self):
        with self.assertRaises(OKXMetadataError):
            calc_contract_size("ETH", 1000, 0.10, 2.5, {})

    def test_build_metadata_alerts_only_reports_tracked_coins(self):
        alerts = _build_metadata_alerts({
            "SOL-USDT-SWAP": "missing ctVal",
            "DOGE-USDT-SWAP": "missing lotSz",
        })

        self.assertIn("SOL", alerts)
        self.assertNotIn("DOGE", alerts)


if __name__ == "__main__":
    unittest.main()
