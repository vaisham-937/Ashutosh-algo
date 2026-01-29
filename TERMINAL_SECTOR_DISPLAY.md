# Monitor Log - Sector Display Added ✅

## Feature
Added colored sector information to the "MONITOR" logs in the terminal/console.

## Changes

### 1. Added Color Helper
Added `_bg_magenta` helper for formatting sector badges in terminal.

### 2. Updated Trigger Log
The `📈 MONITOR` line now includes the sector name if available.

**Before:**
```
📈 MONITOR  MANAPPURAM  alert=test scan
```

**After:**
```
📈 MONITOR  MANAPPURAM  [NIFTY AUTO]  alert=test scan
```
*(Sector name appears in Magenta background)*

## How to Test
1. Run the application
2. Open a position for a stock in the mapping (e.g. `MANAPPURAM` -> `NIFTY FIN SERVICE`)
3. Watch the terminal logs
4. You should see the sector badge appear in the periodic monitor box.

## Visuals
- **Stock Symbol**: Blue Background (existing)
- **Sector Name**: **Magenta Background** (NEW)
- **Alert Name**: Dimmed text

This provides immediate visual context about which sector the tracked stock belongs to directly in the logs! 🚀
