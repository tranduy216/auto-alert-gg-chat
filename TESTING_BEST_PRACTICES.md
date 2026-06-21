# Testing Best Practices

**Last Updated:** 2026-06-21  
**Purpose:** Guidelines for effective backtesting and validation

---

## 🎯 Core Principles

### 1. **Too Good to Be True Check**
**Problem:** Backtest results that seem unrealistic

**Solution:**
```python
# RED FLAGS - Question these results:
- CAGR > 100% (especially > 200%)
- Max DD < 10% with high leverage
- Win rate > 80%
- Profit factor > 5
- Sharpe ratio > 3

# VALIDATION STEPS:
1. Check for data snooping (using future data)
2. Verify transaction costs are included
3. Check for survivorship bias
4. Validate with out-of-sample data
5. Compare with buy & hold baseline
```

**Example:**
```python
# ❌ BAD: CAGR 282% with 53% DD (too risky)
# ✅ GOOD: CAGR 54% with 25% DD (realistic)
```

---

## 💾 Caching Strategy

### 2. **Data Caching**
**Problem:** Repeated API calls slow down testing

**Solution:**
```python
# Cache structure
cache/
├── klines/
│   ├── BTCUSDT_1D_1000.json
│   ├── ETHUSDT_1D_1000.json
│   └── ...
└── backtest_results/
    ├── config_hash_123.json
    └── config_hash_456.json

# Cache key generation
def generate_cache_key(symbol, config):
    config_str = json.dumps(config, sort_keys=True)
    config_hash = hashlib.md5(config_str.encode()).hexdigest()[:8]
    return f"{symbol}_{config_hash}"
```

**Benefits:**
- 10-100x faster iteration
- Consistent results across runs
- Reduced API rate limit issues

---

### 3. **Execution Caching**
**Problem:** Re-running same backtest configuration

**Solution:**
```python
class BacktestCache:
    def __init__(self, cache_dir='cache/backtest_results'):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def get_or_compute(self, symbol, config, compute_fn):
        cache_key = self.generate_cache_key(symbol, config)
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        if cache_file.exists():
            # Load from cache
            with open(cache_file) as f:
                return json.load(f)
        else:
            # Compute and cache
            result = compute_fn(symbol, config)
            with open(cache_file, 'w') as f:
                json.dump(result, f)
            return result
```

**Usage:**
```python
cache = BacktestCache()
result = cache.get_or_compute('BTC', config, backtest_fn)
```

---

## ⚡ Parallel Execution

### 4. **Multi-Processing for Backtests**
**Problem:** Sequential backtests are slow

**Solution:**
```python
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp

def parallel_backtest(symbols, config, max_workers=None):
    """Run backtests in parallel"""
    if max_workers is None:
        max_workers = mp.cpu_count()
    
    results = {}
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all jobs
        futures = {
            executor.submit(backtest_coin_yearly, symbol, config): symbol
            for symbol in symbols
        }
        
        # Collect results
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                results[symbol] = future.result()
            except Exception as e:
                print(f"Error backtesting {symbol}: {e}")
                results[symbol] = None
    
    return results

# Usage
symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']
results = parallel_backtest(symbols, config, max_workers=4)
```

**Performance:**
- Sequential: 3 coins × 30s = 90s
- Parallel (4 cores): 3 coins × 30s / 4 = ~23s
- **Speedup: ~4x**

---

### 5. **Vectorized Operations**
**Problem:** Loop-based calculations are slow

**Solution:**
```python
# ❌ SLOW: Loop-based
def calculate_returns_slow(prices):
    returns = []
    for i in range(1, len(prices)):
        ret = (prices[i] - prices[i-1]) / prices[i-1]
        returns.append(ret)
    return returns

# ✅ FAST: Vectorized with numpy
import numpy as np

def calculate_returns_fast(prices):
    prices = np.array(prices)
    returns = np.diff(prices) / prices[:-1]
    return returns.tolist()
```

**Performance:**
- Loop: 1000 elements → 10ms
- Vectorized: 1000 elements → 0.1ms
- **Speedup: ~100x**

---

## 📊 Code Coverage

### 6. **Unit Test Coverage**
**Problem:** Untested code has bugs

**Solution:**
```bash
# Run tests with coverage
pytest --cov=scripts --cov-report=html tests/

# View coverage report
open htmlcov/index.html

# Target: > 80% coverage
```

**Coverage priorities:**
1. **Critical paths** (100% coverage):
   - Position sizing logic
   - Risk management
   - Stop loss calculations
   - Entry/exit signals

2. **Important paths** (> 80% coverage):
   - Indicator calculations
   - Data fetching
   - Configuration loading

3. **Utility functions** (> 60% coverage):
   - Helper functions
   - Data transformations

---

### 7. **Integration Test Coverage**
**Problem:** Components work individually but fail together

**Solution:**
```python
def test_full_trading_workflow():
    """Test complete trading workflow"""
    # 1. Load data
    candles = load_candles('BTCUSDT', '1D', 1000)
    
    # 2. Run backtest
    result = backtest_coin_yearly(candles, 'BTC', config)
    
    # 3. Validate results
    assert result['final_equity'] > 10000
    assert result['max_drawdown'] < 50
    assert result['cagr'] > 0
    
    # 4. Check trades
    assert len(result['trades']) > 0
```

---

## 🔍 Validation Checklist

### 8. **Backtest Validation**
**Before trusting results, verify:**

```python
def validate_backtest(result):
    """Validate backtest results"""
    checks = {
        'CAGR reasonable': 0 < result['cagr'] < 100,
        'Max DD reasonable': 0 <= result['max_drawdown'] < 100,
        'Final equity positive': result['final_equity'] > 0,
        'Has trades': len(result['trades']) > 0,
        'Win rate reasonable': 0.2 < result['win_rate'] < 0.8,
        'Profit factor reasonable': 0.5 < result['profit_factor'] < 5,
    }
    
    for check_name, passed in checks.items():
        status = '✅' if passed else '❌'
        print(f"{status} {check_name}")
    
    return all(checks.values())
```

---

### 9. **Out-of-Sample Testing**
**Problem:** Overfitting to historical data

**Solution:**
```python
# Split data into train/test
train_data = candles[:int(len(candles) * 0.7)]  # 70% train
test_data = candles[int(len(candles) * 0.7):]   # 30% test

# Optimize on train data
best_config = optimize_config(train_data)

# Validate on test data (out-of-sample)
test_result = backtest_coin_yearly(test_data, 'BTC', best_config)

# Compare train vs test performance
train_result = backtest_coin_yearly(train_data, 'BTC', best_config)

print(f"Train CAGR: {train_result['cagr']:.2f}%")
print(f"Test CAGR: {test_result['cagr']:.2f}%")

# If test CAGR << train CAGR → overfitting
if test_result['cagr'] < train_result['cagr'] * 0.5:
    print("⚠️ WARNING: Possible overfitting!")
```

---

### 10. **Monte Carlo Simulation**
**Problem:** Single backtest doesn't show variance

**Solution:**
```python
def monte_carlo_simulation(result, n_simulations=1000):
    """Simulate trade order randomness"""
    trades = result['trades']
    final_equities = []
    
    for _ in range(n_simulations):
        # Shuffle trade order
        shuffled_trades = trades.copy()
        random.shuffle(shuffled_trades)
        
        # Calculate equity curve
        equity = 10000
        for trade in shuffled_trades:
            equity *= (1 + trade['return'])
        
        final_equities.append(equity)
    
    # Calculate statistics
    mean_equity = np.mean(final_equities)
    std_equity = np.std(final_equities)
    percentile_5 = np.percentile(final_equities, 5)
    percentile_95 = np.percentile(final_equities, 95)
    
    print(f"Mean final equity: ${mean_equity:,.2f}")
    print(f"Std deviation: ${std_equity:,.2f}")
    print(f"5th percentile: ${percentile_5:,.2f}")
    print(f"95th percentile: ${percentile_95:,.2f}")
```

---

## 🐛 Common Pitfalls

### 11. **Look-Ahead Bias**
**Problem:** Using future data in past decisions

**❌ BAD:**
```python
# Using future data to make past decisions
for i in range(len(candles)):
    # ❌ Looking at future candles
    future_high = max(c['high'] for c in candles[i:i+10])
    if candles[i]['close'] < future_high * 0.9:
        # Buy signal based on future data
        buy()
```

**✅ GOOD:**
```python
# Only use past data
for i in range(len(candles)):
    # ✅ Only look at past candles
    past_high = max(c['high'] for c in candles[:i+1])
    if candles[i]['close'] < past_high * 0.9:
        # Buy signal based on past data
        buy()
```

---

### 12. **Survivorship Bias**
**Problem:** Only testing on coins that survived

**❌ BAD:**
```python
# Only test on current top coins
coins = ['BTC', 'ETH', 'BNB']  # Survivors
```

**✅ GOOD:**
```python
# Include delisted coins
coins = ['BTC', 'ETH', 'BNB', 'LUNA', 'FTT']  # Including failures
```

---

### 13. **Transaction Cost Ignorance**
**Problem:** Ignoring fees and slippage

**❌ BAD:**
```python
# No transaction costs
pnl = (exit_price - entry_price) * position_size
```

**✅ GOOD:**
```python
# Include fees and slippage
entry_cost = entry_price * position_size * 0.001  # 0.1% fee
exit_cost = exit_price * position_size * 0.001    # 0.1% fee
slippage = entry_price * position_size * 0.0005   # 0.05% slippage

pnl = (exit_price - entry_price) * position_size - entry_cost - exit_cost - slippage
```

---

## 📈 Performance Optimization

### 14. **Memory Optimization**
**Problem:** Loading too much data into memory

**Solution:**
```python
# ❌ BAD: Load all data at once
all_candles = load_all_candles()  # 10GB memory

# ✅ GOOD: Load in chunks
def process_candles_in_chunks(symbols, chunk_size=100):
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i+chunk_size]
        candles = load_candles(chunk)
        process(candles)
        # Memory freed after each chunk
```

---

### 15. **Database Indexing**
**Problem:** Slow database queries

**Solution:**
```python
# Create indexes for frequently queried fields
db.collection('backtest_results').create_index([
    ('symbol', 1),
    ('timestamp', -1)
])

# Use indexes in queries
results = db.collection('backtest_results').find({
    'symbol': 'BTC',
    'timestamp': {'$gte': start_time}
}).sort('timestamp', -1)
```

---

## 🎓 Summary

### Testing Checklist

- [ ] **Data Caching:** Cache klines and backtest results
- [ ] **Parallel Execution:** Use multiprocessing for speed
- [ ] **Code Coverage:** > 80% for critical paths
- [ ] **Too Good to Be True:** Validate unrealistic results
- [ ] **Out-of-Sample Testing:** Prevent overfitting
- [ ] **Monte Carlo Simulation:** Understand variance
- [ ] **Look-Ahead Bias:** Only use past data
- [ ] **Survivorship Bias:** Include delisted coins
- [ ] **Transaction Costs:** Include fees and slippage
- [ ] **Memory Optimization:** Process in chunks

### Performance Targets

| Metric | Target | Priority |
|--------|--------|----------|
| Code coverage | > 80% | High |
| Backtest speed | < 30s per coin | Medium |
| Cache hit rate | > 90% | Medium |
| Test execution | < 5 min | Medium |
| Memory usage | < 4GB | Low |

---

**Last Updated:** 2026-06-21  
**Status:** ✅ Active  
**Next Review:** 2026-07-21
