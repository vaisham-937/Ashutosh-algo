# Fix for Blank LTP, % Change, Buy Qty, Sell Qty Columns

## Issue Description
The alert signals table was showing "--" (blank values) for:
- LTP (Last Traded Price)
- % Change
- Buy Qty (Total Buy Quantity)
- Sell Qty (Total Sell Quantity)

## Root Cause
The WebSocket tick handler was only updating LTP and % Change fields, but:
1. **Missing Buy/Sell Qty Updates**: The handler wasn't updating the `atbq-${symbol}` and `atsq-${symbol}` elements
2. **Missing Color Coding**: % Change wasn't getting proper color classes (green for positive, red for negative)
3. **No Quantity Formatting**: Large quantities weren't being formatted with K/L/Cr suffixes

## Fix Applied

### Enhanced WebSocket Tick Handler
Updated the tick message handler in `dashboard.html` to:

1. **Update All Fields**:
   - LTP with dynamic color (green if up, red if down)
   - % Change with proper color coding
   - Buy Qty with emerald color and K/L/Cr formatting
   - Sell Qty with rose color and K/L/Cr formatting

2. **Smart Quantity Formatting**:
   ```javascript
   const formatQty = (qty) => {
     const q = Number(qty || 0);
     if (q >= 10000000) return (q / 10000000).toFixed(2) + 'Cr';
     if (q >= 100000) return (q / 100000).toFixed(2) + 'L';
     if (q >= 1000) return (q / 1000).toFixed(2) + 'K';
     return q.toFixed(0);
   };
   ```

3. **Color Coding**:
   - **LTP**: Green (up) / Red (down) / Gray (unchanged)
   - **% Change**: Green (positive) / Red (negative) / Gray (zero)
   - **Buy Qty**: Emerald green with 70% opacity
   - **Sell Qty**: Rose red with 70% opacity

## Backend Verification
✅ Backend already sends all required data:
- `ltp`: Last traded price
- `close`: Previous close price
- `tbq`: Total buy quantity
- `tsq`: Total sell quantity

The data is broadcast via WebSocket from `main.py` line 417-429.

## Expected Result
After this fix, when you receive alerts and WebSocket ticks:
- **LTP** will show the current price with color coding
- **% Change** will show percentage change from previous close with color
- **Buy Qty** will show formatted buy quantity (e.g., "1.5K", "2.3L")
- **Sell Qty** will show formatted sell quantity (e.g., "500", "1.2K")

All values will update in real-time as ticks arrive from the KiteTicker WebSocket.

## Testing Steps
1. Refresh the dashboard page
2. Trigger a test alert with some symbols
3. Verify that LTP, % Change, Buy Qty, and Sell Qty columns populate with live data
4. Watch for real-time updates as market data flows in

## Files Modified
- `app/static/dashboard.html` - Enhanced WebSocket tick handler (lines 1137-1186)
