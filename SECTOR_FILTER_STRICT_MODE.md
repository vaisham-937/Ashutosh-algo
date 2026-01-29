# Sector Filter - Strict Mode Enabled ✅

## Issue
When sector filter was ON with `top_n_sector = 1`, stocks from sectors OTHER than the top 1 gainer were still being processed by the trading engine. This violated the expected behavior.

## Root Cause
The sector filter had **lenient fallback logic** that allowed unknown stocks (not in STOCK_INDEX_MAPPING) by default:

```python
# OLD CODE - TOO LENIENT
sec = self.sym_sector.get(symbol)
if not sec:
    log.info("ℹ️ SECTOR_UNKNOWN | symbol=%s (not in mapping, allowing by default)", symbol)
    return True  # ❌ This allowed unknown stocks!
```

## Fix Applied - STRICT Mode

### Changed Behavior:
**Before**: Unknown stocks → ✅ ALLOWED  
**After**: Unknown stocks → ❌ REJECTED

### New Code:
```python
sec = self.sym_sector.get(symbol)

if not sec:
    # Try to help debug - show similar symbols
    available_symbols = [s for s in self.sym_sector.keys() if symbol.upper() in s.upper() or s.upper() in symbol.upper()]
    log.warning(
        "❌ SECTOR_UNKNOWN | symbol='%s' (not in STOCK_INDEX_MAPPING with %d stocks, REJECTING) | Similar: %s",
        symbol, len(self.sym_sector), available_symbols[:3] if available_symbols else "none"
    )
    return False  # STRICT: Reject unknown stocks when filter is ON
```

## How It Works Now

### With Sector Filter ON + Top N = 1:

1. **Alert arrives** with 10 stocks from various sectors
2. **For each stock:**
   - Normalize symbol (e.g., "NSE:SBIN" → "SBIN")
   - Look up in `STOCK_INDEX_MAPPING`
   - **If NOT FOUND** → ❌ **REJECT** (new behavior)
   - **If FOUND** → Check sector ranking
3. **Get sector rankings**:
   ```
   1. NIFTY PVT BANK: +1.25%  ← Top 1 (ALLOWED)
   2. NIFTY IT: +0.85%        ← Not in top 1 (REJECTED)
   3. NIFTY AUTO: +0.05%      ← Not in top 1 (REJECTED)
   ```
4. **Filter stocks**:
   - SBIN (NIFTY PSU BANK = rank 1) → ✅ PASS
   - TCS (NIFTY IT = rank 2) → ❌ REJECT
   - MARUTI (NIFTY AUTO = rank 3) → ❌ REJECT
   - NEWSTOCK (not in mapping) → ❌ REJECT (strict mode)

## Important: Symbol Matching

### Potential Issue - Normalization Mismatch

**IMPORTANT**: `STOCK_INDEX_MAPPING` keys must match the normalized symbol format!

#### Example of CORRECT mapping:
```python
STOCK_INDEX_MAPPING = {
    'SBIN': 'NIFTY PSU BANK',      # ✅ Normalized form
    'M&M': 'NIFTY AUTO',            # ✅ Keeps & character
    'BAJAJ-AUTO': 'NIFTY AUTO',     # ✅ Keeps - character
}
```

#### Example of WRONG mapping:
```python
STOCK_INDEX_MAPPING = {
    'NSE:SBIN': 'NIFTY PSU BANK',   # ❌ Will not match (prefix removed)
    'SBIN-EQ': 'NIFTY PSU BANK',    # ❌ Will not match (-EQ removed)
    'm&m': 'NIFTY AUTO',            # ❌ Will not match (lowercase)
}
```

### Symbol Normalization Process:

Alert sends: `"NSE:SBIN-EQ"` or `"SBIN"` or `"nse:sbin-eq"`

↓ `_safe_symbol()` / `norm_symbol()`

Normalized to: `"SBIN"`

↓ Lookup in `STOCK_INDEX_MAPPING`

Must match exact key: `'SBIN'`

## Debugging Unknown Stocks

### Check the Logs:
When a stock is rejected, you'll see:
```
❌ SECTOR_UNKNOWN | symbol='NEWSTOCK' (not in STOCK_INDEX_MAPPING with 300 stocks, REJECTING) | Similar: none
```

### If You See This:
1. **Stock is genuinely not in mapping** → Add it to `stock_sector.py`
2. **Normalization mismatch** → Check if the key in `STOCK_INDEX_MAPPING` is uppercase and without prefixes

### Example - Adding Missing Stock:
```python
# In app/stock_sector.py
STOCK_INDEX_MAPPING = {
    # ... existing stocks ...
    'NEWSTOCK': 'NIFTY APPROPRIATE SECTOR',  # Add here
}
```

## Logs You'll See

### Strict Rejection (Unknown Stock):
```
❌ SECTOR_UNKNOWN | symbol='RANDOMSTOCK' (not in STOCK_INDEX_MAPPING with 300 stocks, REJECTING) | Similar: none
```

### Strict Rejection (Wrong Sector):
```
================================================================================
📊 SECTOR RANKINGS (Top 1 for LONG)
================================================================================
🔝 TOP 1 GAINERS (ALLOWED for LONG):
   1. NIFTY PVT BANK: +1.25%

📉 BOTTOM SECTORS (REJECTED for LONG):
   2. NIFTY IT: +0.85%
   3. NIFTY AUTO: +0.05%
   ...
================================================================================

❌ SECTOR_REJECT | symbol=TCS sector=NIFTY IT (+0.85%) | Rank #2 (not in TOP 1)
```

### Pass (Correct Sector):
```
✅ SECTOR_PASS | symbol=SBIN sector=NIFTY PSU BANK (+1.25%) | Rank in TOP 1 gainers
```

## Benefits of Strict Mode

1. ✅ **Precise Control** - Only stocks from top N sectors are traded
2. ✅ **No Leakage** - Unknown stocks don't slip through
3. ✅ **Clear Logs** - Easy to see why stocks are rejected
4. ✅ **Forces Mapping** - Encourages maintaining complete STOCK_INDEX_MAPPING

## Testing

### Test Case 1: Unknown Stock
1. Send alert with stock not in mapping (e.g., "RANDOMXYZ")
2. **Expected**: Stock rejected with "SECTOR_UNKNOWN" message

### Test Case 2: Wrong Sector
1. Set sector filter ON, top N = 1
2. Send alert with stocks from multiple sectors
3. **Expected**: Only stocks from rank #1 sector are traded

### Test Case 3: All Stocks Match
1. Set sector filter ON, top N = 2
2. Send alert with stocks only from top 2 sectors
3. **Expected**: All stocks are traded

## Configuration

### Disable Strict Mode (Allow All):
Set sector filter OFF in alert configuration:
```
Sector Filter: OFF
```

### Moderate Strictness:
Increase top N:
```
Sector Filter: ON
Top N Sectors: 3  (allows top 3 sectors)
```

### Maximum Strictness:
```
Sector Filter: ON
Top N Sectors: 1  (only THE top sector)
```

## Summary

**OLD Behavior** (Lenient):
- Unknown stocks: ✅ Allowed
- Result: Sector filter could be bypassed

**NEW Behavior** (Strict):
- Unknown stocks: ❌ Rejected
- Result: Only stocks from top N sectors AND in mapping are traded

This ensures **precise sector-based filtering** as intended! 🎯
