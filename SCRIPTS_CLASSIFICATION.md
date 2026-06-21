# Scripts Classification

## Production Scripts (KEEP)
- crypto_trading.py - Main trading bot
- breaking_news.py - News alerts
- rss_digest.py - RSS feed processing  
- reset_states.py - Reset trading states
- optimize_profile.py - Profile optimization

## Utility Scripts (KEEP)
- utils/backtest_cache.py - Backtest caching
- utils/discord_webhook.py - Discord notifications
- utils/firebase_utils.py - Firebase integration
- utils/gemini_utils.py - Gemini AI
- utils/okx_utils.py - OKX API
- utils/retry_utils.py - Retry logic
- utils/url_shortener.py - URL shortening
- utils/article_prefilter.py - Article filtering

## Framework Scripts (KEEP & REFACTOR)
- backtest_optimal.py - Backtest framework (refactor to reusable)
- validate_backtest.py - Validation utilities (refactor)

## Test/Analysis Scripts (DELETE)
- analyze_*.py - One-time analysis
- backtest_v*.py - Version-specific backtests
- test_*.py - Ad-hoc tests (replace with unit tests)
- debug_*.py - Debug scripts
- compare_*.py - Comparison scripts
- calculate_*.py - Calculation scripts

## Action Plan
1. Delete all test/analysis scripts
2. Create comprehensive unit tests in tests/
3. Refactor backtest_optimal.py to reusable framework
4. Create best practices documentation
5. Create baseline documentation
