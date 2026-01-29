# Active Positions - Sector Display Feature ✅

## What Was Added

Sector/index information is now displayed in the Active Positions table, showing which sector each stock belongs to.

---

## Changes Made

### 1. Backend - Position Data Structure (`app/trade_engine.py`)

#### Added Sector Field to Position:
```python
@dataclass
class Position:
    # ... existing fields ...
    sector: str = ""  # Sector/index group the stock belongs to
```

#### Set Sector When Creating Position:
```python
pos.sector = self.sym_sector.get(symbol, "")  # Add sector info
```

### 2. Frontend - Display Sector Badge (`app/static/dashboard.html`)

Updated the SYMBOL column to show a sector badge before the symbol:

**Before:**
```html
<td class="font-bold text-white font-mono">${p.symbol}</td>
```

**After:**
```html
<td class="font-bold text-white font-mono">
  ${p.sector ? `<span class="inline-block px-2 py-0.5 mr-2 text-[9px] font-semibold rounded bg-blue-500/10 text-blue-300 border border-blue-500/20">${p.sector}</span>` : ''}
  ${p.symbol}
</td>
```

---

## How It Looks

### Active Positions Table Display:

```
┌─────────────────────────────────────────────────────┐
│ SYMBOL                    │ STRATEGY  │ SIDE  │ ... │
├─────────────────────────────────────────────────────┤
│ [NIFTY AUTO] MARUTI       │ test scan │ BUY   │ ... │
│ [NIFTY IT] TCS            │ breakout  │ BUY   │ ... │
│ [NIFTY PVT BANK] HDFC     │ test scan │ SELL  │ ... │
└─────────────────────────────────────────────────────┘
```

### Visual Appearance:
- **Sector Badge**: Small blue badge with sector name
- **Position**: Before (in front of) the stock symbol
- **Style**: Blue background with blue text and border
- **Font**: Small (9px) for compact display

---

## Sector Examples

Based on your `STOCK_INDEX_MAPPING`:

| Stock | Sector Badge |
|-------|--------------|
| MARUTI | NIFTY AUTO |
| TCS | NIFTY IT |
| SBIN | NIFTY PSU BANK |
| HDFC | NIFTY PVT BANK |
| RELIANCE | NIFTY ENERGY |
| INFY | NIFTY IT |
| M&M | NIFTY AUTO |
| WIPRO | NIFTY IT |

---

## Benefits

1. **Quick Identification** - Instantly see which sector a stock belongs to
2. **Sector Diversification** - Easy to spot if all positions are in same sector
3. **Risk Management** - Helps identify sector concentration risk
4. **Filter Verification** - Confirms sector filter is working correctly
5. **Visual Organization** - Groups similar stocks visually

---

## Different Sector Colors (Optional Enhancement)

If you want different colors for different sector types in the future:

```javascript
// Example: Different colors by sector type
const getSectorColor = (sector) => {
  if (sector.includes('BANK')) return 'bg-green-500/10 text-green-300 border-green-500/20';
  if (sector.includes('IT')) return 'bg-blue-500/10 text-blue-300 border-blue-500/20';
  if (sector.includes('AUTO')) return 'bg-orange-500/10 text-orange-300 border-orange-500/20';
  if (sector.includes('ENERGY')) return 'bg-yellow-500/10 text-yellow-300 border-yellow-500/20';
  return 'bg-slate-500/10 text-slate-300 border-slate-500/20';
};
```

---

## What If Sector Is Unknown?

If a stock is not in `STOCK_INDEX_MAPPING`:
- `pos.sector` will be empty string `""`
- No badge will be displayed
- Only the stock symbol shows (same as before)

**Example:**
```
SYMBOL column:
NEWSTOCK  (no sector badge - stock not in mapping)
```

---

## Data Flow

1. **Trade Entry** → `_try_enter()` creates Position
2. **Sector Lookup** → `self.sym_sector.get(symbol, "")` from `STOCK_INDEX_MAPPING`
3. **Set Field** → `pos.sector = "NIFTY AUTO"` (example)
4. **Save to Redis** → Position with sector info stored
5. **Send to Frontend** → `pos.to_public()` includes sector
6. **Display** → Dashboard renders sector badge before symbol

---

## Testing

### Test 1: Open Position
1. Enter a trade for a stock in your mapping (e.g., MARUTI)
2. Check Active Positions table
3. **Expected**: `[NIFTY AUTO] MARUTI` displayed

### Test 2: Multiple Sectors
1. Open trades in different sectors (IT, AUTO, BANK)
2. Check Active Positions table
3. **Expected**: Each position shows its sector badge

### Test 3: Unknown Stock
1. Enter trade for stock NOT in mapping
2. Check Active Positions table
3. **Expected**: Only stock symbol shows (no badge)

---

## Summary

**Before:**
```
SYMBOL: MANAPPURAM
```

**After:**
```
SYMBOL: [NIFTY FINSEREXBNK] MANAPPURAM
```

✅ Sector information is now visible in Active Positions table  
✅ Helps identify sector exposure at a glance  
✅ Works with existing sector filter functionality  
✅ Clean, compact badge design  

**Refresh your browser to see the sector badges!** 🎯
