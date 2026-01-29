# Sector Filter Feature - How It Works

## Overview
The **Sector Filter** is a smart feature that helps you trade only the **strongest** or **weakest** sectors in the market, based on real-time performance.

## Your Settings
- **Sector Filter**: ON
- **Top N Sectors**: 2
- **Direction**: LONG or SHORT (from your alert config)

---

## How It Works Step-by-Step

### 1️⃣ **Real-Time Sector Performance Tracking**

The system continuously monitors **live price movements** for all stocks in your universe (defined in `stock_sector.py`):

```
NIFTY BANK:     +1.2%  (HDFC, ICICI, SBI, Kotak, Axis, IndusInd)
NIFTY IT:       +0.8%  (TCS, Infosys, HCL, Wipro, Tech M)
NIFTY AUTO:     -0.3%  (Maruti, M&M, Tata Motors, Bajaj Auto)
NIFTY PHARMA:   -0.5%  (Sun Pharma, Dr Reddy's, Cipla)
NIFTY METAL:    -1.1%  (Tata Steel, Hindalco, JSW Steel)
```

**How it calculates**:
- Every tick updates each stock's % change from previous close
- Stocks are grouped by sector (e.g., SBIN → NIFTY BANK)
- Sector performance = **Average % change** of all stocks in that sector

### 2️⃣ **Dynamic Sector Ranking**

The system ranks sectors from **best to worst** performers:

```
Rank 1: NIFTY BANK      +1.2%  ← Top Gainer
Rank 2: NIFTY IT        +0.8%  ← Top Gainer
Rank 3: NIFTY AUTO      -0.3%
Rank 4: NIFTY PHARMA    -0.5%
Rank 5: NIFTY METAL     -1.1%  ← Top Loser
```

### 3️⃣ **Trade Filtering Based on Direction**

When Chartink sends an alert with a stock symbol, the system checks:

#### **For LONG (Buy) Trades**:
✅ **ALLOWED**: Only stocks from **Top 2 Gainers**
- Example: Alert for `SBIN` (NIFTY BANK, Rank 1) → ✅ **TRADE ALLOWED**
- Example: Alert for `TCS` (NIFTY IT, Rank 2) → ✅ **TRADE ALLOWED**
- Example: Alert for `MARUTI` (NIFTY AUTO, Rank 3) → ❌ **REJECTED** (not in top 2)

#### **For SHORT (Sell) Trades**:
✅ **ALLOWED**: Only stocks from **Bottom 2 Losers**
- Example: Alert for `TATASTEEL` (NIFTY METAL, Rank 5) → ✅ **TRADE ALLOWED**
- Example: Alert for `DRREDDY` (NIFTY PHARMA, Rank 4) → ✅ **TRADE ALLOWED**
- Example: Alert for `SBIN` (NIFTY BANK, Rank 1) → ❌ **REJECTED** (not in bottom 2)

---

## Real-World Example

### Scenario: Market Opens
```
09:15 AM - Initial Rankings:
1. NIFTY BANK:  +0.5%
2. NIFTY IT:    +0.3%
3. NIFTY AUTO:  +0.1%
4. NIFTY PHARMA: -0.2%
5. NIFTY METAL:  -0.4%
```

### Chartink Sends Alerts:
1. **Alert for SBIN** (NIFTY BANK) → ✅ **ALLOWED** (Rank 1, Top 2 gainer)
2. **Alert for INFY** (NIFTY IT) → ✅ **ALLOWED** (Rank 2, Top 2 gainer)
3. **Alert for MARUTI** (NIFTY AUTO) → ❌ **REJECTED** (Rank 3, not in top 2)

### 10:30 AM - Rankings Change:
```
1. NIFTY IT:    +1.2%  ← Now #1
2. NIFTY AUTO:  +0.9%  ← Moved up!
3. NIFTY BANK:  +0.4%  ← Dropped to #3
4. NIFTY PHARMA: -0.1%
5. NIFTY METAL:  -0.6%
```

### New Alerts:
1. **Alert for TCS** (NIFTY IT) → ✅ **ALLOWED** (Now Rank 1)
2. **Alert for MARUTI** (NIFTY AUTO) → ✅ **ALLOWED** (Now Rank 2)
3. **Alert for SBIN** (NIFTY BANK) → ❌ **REJECTED** (Now Rank 3, dropped out)

---

## Why Use This Feature?

### ✅ **Benefits**:
1. **Trade with momentum** - Only enter sectors showing strength
2. **Avoid weak sectors** - Skip stocks in underperforming sectors
3. **Better win rate** - Align with market flow
4. **Risk management** - Don't fight the trend

### 📊 **Statistics**:
- **Without filter**: Trade all Chartink alerts (could be 20-30 stocks)
- **With Top 2 filter**: Trade only 2 strongest sectors (typically 6-8 stocks)

---

## Configuration Options

### **Top N Sectors = 1**
- Most aggressive filtering
- Only trade THE strongest sector
- Example: Only NIFTY BANK if it's #1

### **Top N Sectors = 2** (Your Setting)
- Balanced approach
- Trade top 2 strongest sectors
- Example: NIFTY BANK + NIFTY IT

### **Top N Sectors = 3**
- More relaxed filtering
- Trade top 3 sectors
- More opportunities, slightly less selective

---

## Important Notes

### 🔄 **Dynamic Updates**
- Rankings update **every tick** (real-time)
- A sector can move from #1 to #5 within minutes
- System adapts automatically

### 📍 **Unknown Stocks**
If a stock is **not in the mapping** (`stock_sector.py`):
- ✅ **ALLOWED by default** (no rejection)
- Add it to `STOCK_INDEX_MAPPING` if you want it filtered

### 🎯 **Works Per Alert**
Each alert configuration has its own sector filter setting:
- Alert A: Sector Filter ON, Top 2
- Alert B: Sector Filter OFF (trades all)
- Alert C: Sector Filter ON, Top 1

---

## Log Messages

When sector filter rejects a trade, you'll see:
```
🚫 SECTOR_BLOCK | user=1 alert=bullish_breakout symbol=MARUTI 
   sector=NIFTY AUTO topN=2 dir=LONG
```

This means:
- MARUTI belongs to NIFTY AUTO
- NIFTY AUTO is NOT in top 2 gainers
- Trade rejected

---

## Summary

**With Sector Filter ON + Top N = 2**:
- ✅ You trade ONLY the **2 strongest sectors** (for LONG)
- ✅ You trade ONLY the **2 weakest sectors** (for SHORT)
- ✅ Rankings update in **real-time** based on live prices
- ✅ Helps you **follow market momentum**
- ✅ Reduces noise and improves trade quality

**Turn it OFF** if you want to trade all Chartink alerts regardless of sector performance.
