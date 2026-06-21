"""
Pytest configuration and fixtures for crypto trading tests
"""
import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch
from datetime import datetime


@pytest.fixture
def sample_candle():
    """Sample candle data for testing"""
    return {
        'timestamp': 1609459200000,
        'open': 100.0,
        'high': 110.0,
        'low': 90.0,
        'close': 105.0,
        'volume': 10000.0
    }


@pytest.fixture
def sample_candles():
    """Sample candle series for testing"""
    return [
        {'timestamp': 1609459200000 + i*86400000, 
         'open': 100.0 + i*2, 
         'high': 110.0 + i*2, 
         'low': 90.0 + i*2, 
         'close': 105.0 + i*2, 
         'volume': 10000.0 + i*100}
        for i in range(100)
    ]


@pytest.fixture
def sample_position():
    """Sample position for testing"""
    return {
        'symbol': 'BTCUSDT',
        'side': 'long',
        'size': 0.1,
        'entry_price': 50000.0,
        'margin': 5000.0,
        'leverage': 10,
        'unrealized_pnl': 500.0,
        'position_equity': 5500.0
    }


@pytest.fixture
def sample_config():
    """Sample configuration for testing"""
    return {
        'max_position_size': 35000,
        'leverage': 3.5,
        'max_margin': 10000,
        'max_exposure_pct': 1.0,
        'initial_exposure': 0.15,
        'snowball_levels': [1.10, 1.20, 1.30],
        'atr_multiplier': 4.0,
        'trailing_activation': 0.30,
        'trailing_stop_pct': 0.09,
        'trailing_close_pct': 0.70
    }


@pytest.fixture
def mock_okx_client():
    """Mock OKX API client"""
    with patch('scripts.utils.okx_utils.OKXClient') as mock:
        client = Mock()
        client.get_positions.return_value = []
        client.place_order.return_value = {'ordId': '123456'}
        client.get_candles.return_value = []
        mock.return_value = client
        yield client


@pytest.fixture
def mock_firebase():
    """Mock Firebase client"""
    with patch('scripts.utils.firebase_utils.FirebaseClient') as mock:
        client = Mock()
        client.get_state.return_value = {}
        client.update_state.return_value = True
        mock.return_value = client
        yield client


@pytest.fixture
def mock_discord():
    """Mock Discord webhook"""
    with patch('scripts.utils.discord_webhook.send_discord_message') as mock:
        mock.return_value = True
        yield mock


@pytest.fixture
def test_data_path():
    """Path to test data directory"""
    return Path(__file__).parent / 'data'


@pytest.fixture
def cache_path():
    """Path to cache file"""
    return Path(__file__).parent.parent / 'scripts' / '_klines_12h_5y.json'
