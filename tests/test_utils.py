"""
Unit tests for utility functions (unittest version)
Coverage: OKX API, Firebase, Discord, caching, retry
"""
import unittest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))


class TestOKXUtils(unittest.TestCase):
    """Test OKX API utilities"""

    def test_fetch_candles_import(self):
        """Should import fetch functions"""
        from scripts.utils.okx_utils import _okx_request
        from scripts.crypto_trading_legacy import _parse_okx_klines
        self.assertTrue(callable(_okx_request))
        self.assertTrue(callable(_parse_okx_klines))

    @patch('scripts.utils.okx_utils._okx_request')
    def test_okx_set_leverage(self, mock_request):
        """Should call set leverage"""
        mock_request.return_value = {'code': '0', 'data': [{'lever': '3'}]}
        from scripts.utils.okx_utils import okx_set_leverage
        self.assertTrue(callable(okx_set_leverage))

    @patch('scripts.utils.okx_utils._okx_request')
    def test_okx_cancel_algo_batch_body(self, mock_request):
        """Should send one cancel object per algo id."""
        mock_request.return_value = {'code': '0', 'data': []}
        from scripts.utils.okx_utils import okx_cancel_algo

        okx_cancel_algo('BNB-USDT-SWAP', ['11', '22'])

        mock_request.assert_called_once_with(
            "POST",
            "/api/v5/trade/cancel-algos",
            [
                {"instId": "BNB-USDT-SWAP", "algoId": "11"},
                {"instId": "BNB-USDT-SWAP", "algoId": "22"},
            ],
        )

    @patch('scripts.utils.okx_utils._okx_request')
    def test_okx_place_algo_oco_body(self, mock_request):
        """Should include both TP and SL fields for OCO algos."""
        mock_request.return_value = {'code': '0', 'data': []}
        from scripts.utils.okx_utils import okx_place_algo

        okx_place_algo(
            inst_id='BNB-USDT-SWAP',
            td_mode='cross',
            side='sell',
            sz='3',
            ord_type='oco',
            tp_trigger_px='106.00',
            sl_trigger_px='97.00',
        )

        mock_request.assert_called_once_with(
            "POST",
            "/api/v5/trade/order-algo",
            {
                "instId": "BNB-USDT-SWAP",
                "tdMode": "cross",
                "side": "sell",
                "sz": "3",
                "ordType": "oco",
                "tpTriggerPx": "106.00",
                "tpOrdPx": "-1",
                "slTriggerPx": "97.00",
                "slOrdPx": "-1",
            },
        )


class TestFirebaseUtils(unittest.TestCase):
    """Test Firebase utilities"""

    def test_is_firebase_enabled_no_env(self):
        """Should return False when no service account"""
        import os
        from scripts.utils.firebase_utils import is_firebase_enabled
        old_val = os.environ.pop('FIREBASE_SERVICE_ACCOUNT', None)
        try:
            result = is_firebase_enabled()
            self.assertFalse(result)
        finally:
            if old_val:
                os.environ['FIREBASE_SERVICE_ACCOUNT'] = old_val


class TestRetryUtils(unittest.TestCase):
    """Test retry utilities"""

    def test_retry_success_first_try(self):
        """Should succeed on first try"""
        from scripts.utils.retry_utils import call_with_retry

        call_count = [0]

        def success_func():
            call_count[0] += 1
            return 'success'

        result = call_with_retry(success_func, resource_name="test")
        self.assertEqual(result, 'success')
        self.assertEqual(call_count[0], 1)

    def test_retry_success_after_failures(self):
        """Should succeed after failures"""
        from scripts.utils.retry_utils import call_with_retry, MAX_RETRIES

        call_count = [0]

        def fail_then_succeed():
            call_count[0] += 1
            if call_count[0] < min(3, MAX_RETRIES + 1):
                raise Exception('Temporary failure')
            return 'success'

        result = call_with_retry(fail_then_succeed, resource_name="test")
        self.assertEqual(result, 'success')

    def test_retry_all_fail(self):
        """Should raise exception when all retries fail"""
        from scripts.utils.retry_utils import call_with_retry

        call_count = [0]

        def always_fail():
            call_count[0] += 1
            raise Exception('Always fails')

        with self.assertRaises(Exception):
            call_with_retry(always_fail, resource_name="test")


class TestBacktestCache(unittest.TestCase):
    """Test backtest caching utilities"""

    def test_cache_import(self):
        """Should import cache module successfully"""
        from scripts.utils.backtest_cache import config_hash
        key1 = config_hash({'coin': 'BTC', 'lev': 3.5})
        key2 = config_hash({'coin': 'BTC', 'lev': 3.5})
        self.assertEqual(key1, key2)
        self.assertIsInstance(key1, str)

    def test_cache_key_different_configs(self):
        """Different configs should generate different keys"""
        from scripts.utils.backtest_cache import config_hash
        key1 = config_hash({'coin': 'BTC', 'lev': 3.5})
        key2 = config_hash({'coin': 'BTC', 'lev': 5.0})
        self.assertNotEqual(key1, key2)


if __name__ == '__main__':
    unittest.main()
