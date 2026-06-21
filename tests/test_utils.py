"""
Unit tests for utility functions
Coverage: OKX API, Firebase, Discord, caching
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))


class TestOKXUtils:
    """Test OKX API utilities"""
    
    @patch('scripts.utils.okx_utils.requests.get')
    def test_fetch_candles_success(self, mock_get):
        """Should fetch candles successfully"""
        from scripts.utils.okx_utils import fetch_candles
        
        # Mock response
        mock_response = Mock()
        mock_response.json.return_value = {
            'code': '0',
            'data': [
                ['1609459200000', '100', '110', '90', '105', '10000']
            ]
        }
        mock_get.return_value = mock_response
        
        candles = fetch_candles('BTC-USDT', '1D', limit=1)
        
        assert len(candles) > 0
        assert 'timestamp' in candles[0]
        assert 'close' in candles[0]
    
    @patch('scripts.utils.okx_utils.requests.post')
    def test_place_order_success(self, mock_post):
        """Should place order successfully"""
        from scripts.utils.okx_utils import place_order
        
        # Mock response
        mock_response = Mock()
        mock_response.json.return_value = {
            'code': '0',
            'data': [{'ordId': '123456'}]
        }
        mock_post.return_value = mock_response
        
        result = place_order('BTC-USDT', 'buy', 0.1, price=50000)
        
        assert result is not None
        assert 'ordId' in result['data'][0]


class TestFirebaseUtils:
    """Test Firebase utilities"""
    
    @patch('scripts.utils.firebase_utils.firestore')
    def test_get_state_success(self, mock_firestore):
        """Should get state successfully"""
        from scripts.utils.firebase_utils import get_state
        
        # Mock Firestore
        mock_doc = Mock()
        mock_doc.get.return_value.to_dict.return_value = {'key': 'value'}
        mock_firestore.client.return_value.collection.return_value.document.return_value = mock_doc
        
        state = get_state('BTC')
        
        assert state is not None
        assert isinstance(state, dict)
    
    @patch('scripts.utils.firebase_utils.firestore')
    def test_update_state_success(self, mock_firestore):
        """Should update state successfully"""
        from scripts.utils.firebase_utils import update_state
        
        # Mock Firestore
        mock_doc = Mock()
        mock_firestore.client.return_value.collection.return_value.document.return_value = mock_doc
        
        result = update_state('BTC', {'key': 'value'})
        
        assert result is True
        mock_doc.set.assert_called_once()


class TestDiscordWebhook:
    """Test Discord webhook utilities"""
    
    @patch('scripts.utils.discord_webhook.requests.post')
    def test_send_message_success(self, mock_post):
        """Should send message successfully"""
        from scripts.utils.discord_webhook import send_discord_message
        
        # Mock response
        mock_response = Mock()
        mock_response.status_code = 204
        mock_post.return_value = mock_response
        
        result = send_discord_message('Test message', webhook_url='http://test.com')
        
        assert result is True
        mock_post.assert_called_once()
    
    @patch('scripts.utils.discord_webhook.requests.post')
    def test_send_message_failure(self, mock_post):
        """Should handle failure gracefully"""
        from scripts.utils.discord_webhook import send_discord_message
        
        # Mock failure
        mock_response = Mock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response
        
        result = send_discord_message('Test message', webhook_url='http://test.com')
        
        assert result is False


class TestBacktestCache:
    """Test backtest caching utilities"""
    
    def test_cache_key_generation(self):
        """Should generate consistent cache keys"""
        from scripts.utils.backtest_cache import generate_cache_key
        
        config = {'leverage': 3.5, 'initial_exposure': 0.15}
        key1 = generate_cache_key('BTC', config)
        key2 = generate_cache_key('BTC', config)
        
        assert key1 == key2
        assert isinstance(key1, str)
    
    def test_cache_key_different_configs(self):
        """Different configs should generate different keys"""
        from scripts.utils.backtest_cache import generate_cache_key
        
        config1 = {'leverage': 3.5, 'initial_exposure': 0.15}
        config2 = {'leverage': 5.0, 'initial_exposure': 0.15}
        
        key1 = generate_cache_key('BTC', config1)
        key2 = generate_cache_key('BTC', config2)
        
        assert key1 != key2


class TestRetryUtils:
    """Test retry utilities"""
    
    def test_retry_success_first_try(self):
        """Should succeed on first try"""
        from scripts.utils.retry_utils import retry_with_backoff
        
        call_count = [0]
        
        def success_func():
            call_count[0] += 1
            return 'success'
        
        result = retry_with_backoff(success_func, max_retries=3)
        
        assert result == 'success'
        assert call_count[0] == 1
    
    def test_retry_success_after_failures(self):
        """Should succeed after failures"""
        from scripts.utils.retry_utils import retry_with_backoff
        
        call_count = [0]
        
        def fail_then_succeed():
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception('Temporary failure')
            return 'success'
        
        result = retry_with_backoff(fail_then_succeed, max_retries=5, base_delay=0.01)
        
        assert result == 'success'
        assert call_count[0] == 3
    
    def test_retry_max_retries_exceeded(self):
        """Should raise exception after max retries"""
        from scripts.utils.retry_utils import retry_with_backoff
        
        def always_fail():
            raise Exception('Always fails')
        
        with pytest.raises(Exception):
            retry_with_backoff(always_fail, max_retries=3, base_delay=0.01)
