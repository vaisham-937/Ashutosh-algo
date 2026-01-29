# Sector Filter - Enhanced Logging & Verification

## Overview
The sector filter has been enhanced with detailed logging to help you verify it's working correctly and understand which stocks are being filtered.

---

## What Was Added

### 1. **Sector Performance Tracking Logs** 📊
Every time a stock price updates, you'll see (in DEBUG mode):
```
📊 SECTOR_TRACK_NEW | SBIN (NIFTY PSU BANK) = +1.25% | Sector avg now: +1.25%
📊 SECTOR_UPDATE | ICICIBANK (NIFTY PVT BANK) = +0.85% (was +0.75%) | Sector avg: +0.92%
```

### 2. **Periodic Sector Rankings** 📈
Every **2 minutes**, the system logs a complete sector performance summary:
```
================================================================================
📊 SECTOR PERFORMANCE SUMMARY (Updated: 13:45:30)
================================================================================
   1. 🟢 NIFTY PVT BANK          +1.25% (5 stocks)
   2. 🟢 NIFTY IT                +0.85% (10 stocks)
   3. 🟢 NIFTY HEALTHCARE        +0.45% (20 stocks)
   4. ⚪ NIFTY AUTO              +0.05% (15 stocks)
   5. 🔴 NIFTY METAL             -0.35% (15 stocks)
   6. 🔴 NIFTY ENERGY            -0.75% (35 stocks)
================================================================================
```

### 3. **Detailed Filtering Decisions** ✅❌
When Chartink sends an alert, you'll see:

#### **Full Sector Rankings:**
```
================================================================================
📊 SECTOR RANKINGS (Top 2 for LONG)
================================================================================
🔝 TOP 2 GAINERS (ALLOWED for LONG):
   1. NIFTY PVT BANK: +1.25%
   2. NIFTY IT: +0.85%

📉 BOTTOM SECTORS (REJECTED for LONG):
   3. NIFTY HEALTHCARE: +0.45%
   4. NIFTY AUTO: +0.05%
   5. NIFTY METAL: -0.35%
   6. NIFTY ENERGY: -0.75%
================================================================================
```

#### **Individual Stock Decisions:**
```
✅ SECTOR_PASS | symbol=SBIN sector=NIFTY PSU BANK (+1.25%) | Rank in TOP 2 gainers
❌ SECTOR_REJECT | symbol=MARUTI sector=NIFTY AUTO (+0.05%) | Rank #4 (not in TOP 2)
```

### 4. **Unknown Stock Handling** ℹ️
If a stock is not in your sector mapping:
```
ℹ️ SECTOR_UNKNOWN | symbol=NEWSTOCK (not in mapping, allowing by default)
```

---

## How to Verify Sector Filter is Working

### Step 1: Check Startup Logs
After server starts, you should see:
```
[INSTR] Loaded 300+ NSE symbols into memory
[SUB] subscribed tokens=300+ mode=FULL
```

This confirms the base universe is subscribed for sector tracking.

### Step 2: Wait for Sector Data (1-2 minutes)
The system needs live ticks to calculate sector performance. After market opens, you'll start seeing:
```
📊 SECTOR_TRACK_NEW | SBIN (NIFTY PSU BANK) = +0.15%
📊 SECTOR_TRACK_NEW | ICICIBANK (NIFTY PVT BANK) = +0.25%
...
```

### Step 3: Check Periodic Summary
Every 2 minutes, verify the sector summary appears:
```
📊 SECTOR PERFORMANCE SUMMARY (Updated: 13:45:30)
```

### Step 4: Send Test Alert
When Chartink sends an alert, you should see:
1. **Sector Rankings** - Full list showing top N sectors
2. **Individual Decision** - Whether each stock passed or was rejected
3. **Reason** - Clear explanation of why

---

## Example: Full Alert Processing Log

```
2026-01-28 13:45:30 [INFO] 🔔 ALERT_RECEIVED
user=1 alert=bullish_breakout symbols=['SBIN', 'MARUTI', 'TCS', 'TATASTEEL']

2026-01-28 13:45:30 [INFO] ✅ CFG_OK
user=1 alert=bullish_breakout dir=LONG product=MIS sector_filter=True topN=2

================================================================================
📊 SECTOR RANKINGS (Top 2 for LONG)
================================================================================
🔝 TOP 2 GAINERS (ALLOWED for LONG):
   1. NIFTY PVT BANK: +1.25%
   2. NIFTY IT: +0.85%

📉 BOTTOM SECTORS (REJECTED for LONG):
   3. NIFTY HEALTHCARE: +0.45%
   4. NIFTY AUTO: +0.05%
   5. NIFTY METAL: -0.35%
================================================================================

2026-01-28 13:45:30 [INFO] ✅ SECTOR_PASS
symbol=SBIN sector=NIFTY PSU BANK (+1.25%) | Rank in TOP 2 gainers

2026-01-28 13:45:30 [INFO] ❌ SECTOR_REJECT
symbol=MARUTI sector=NIFTY AUTO (+0.05%) | Rank #4 (not in TOP 2)

2026-01-28 13:45:30 [INFO] ✅ SECTOR_PASS
symbol=TCS sector=NIFTY IT (+0.85%) | Rank in TOP 2 gainers

2026-01-28 13:45:30 [INFO] ❌ SECTOR_REJECT
symbol=TATASTEEL sector=NIFTY METAL (-0.35%) | Rank #5 (not in TOP 2)

2026-01-28 13:45:30 [INFO] 📊 ALERT_SUMMARY
entered=2 skipped=2 rejected=0 errors=0 total=4
```

**Result**: Only SBIN and TCS were traded (top 2 sectors). MARUTI and TATASTEEL were filtered out.

---

## Troubleshooting

### Issue: "No sector data available yet"
**Cause**: Market hasn't opened or no ticks received yet  
**Solution**: Wait 1-2 minutes after market opens for data to populate

### Issue: All stocks allowed despite filter ON
**Cause**: Stocks not in `STOCK_INDEX_MAPPING`  
**Solution**: Check logs for "SECTOR_UNKNOWN" messages. Add missing stocks to `stock_sector.py`

### Issue: Wrong sectors being selected
**Cause**: Sector performance calculation issue  
**Solution**: Check periodic summary logs to verify sector rankings are correct

### Issue: No periodic summaries appearing
**Cause**: No ticks being received  
**Solution**: 
1. Check WebSocket connection status
2. Verify Zerodha login is active
3. Check if base universe is subscribed

---

## Configuration

### Change Summary Frequency
In `trade_engine.py`, line ~355:
```python
self.sector_rank_log_interval_sec: float = 120.0  # Change to 60 for 1 min, 300 for 5 min
```

### Enable Debug Logs
To see every sector update (verbose):
```python
logging.getLogger("trade_engine").setLevel(logging.DEBUG)
```

### Disable Sector Filter
In alert configuration:
- Set "Sector Filter" to OFF
- Or set "Top N Sectors" to a very high number (e.g., 50)

---

## Summary

**With Enhanced Logging, You Can Now:**
✅ See real-time sector performance every 2 minutes  
✅ Verify which sectors are top performers  
✅ Understand why each stock was accepted or rejected  
✅ Debug sector filter issues quickly  
✅ Confirm the feature is working as expected  

**Check your terminal logs** to see these messages in action!
