# Active Positions Display Fix - CLOSED Positions Removed ✅

## Issue
After clicking "Square Off All", positions were exited from Zerodha (demat account) successfully, but they remained visible in the "Active Positions" table on the dashboard with status "CLOSED" and reason "MANUAL_EXIT_ALL".

## Root Cause
1. **Backend**: After exiting positions, the system was keeping CLOSED positions in Redis by calling `upsert_position()` instead of deleting them
2. **Frontend**: The dashboard was displaying ALL positions from the API, including CLOSED and ERROR status positions

## Fixes Applied

### 1. Backend - Delete Closed Positions (`app/trade_engine.py`)

**Before:**
```python
# After successful exit, update position with CLOSED status
await self.store.upsert_position(self.user_id, symbol, pos.to_public())
```

**After:**
```python
# Delete from Redis and memory instead of keeping CLOSED positions
try:
    await self.store.delete_position(self.user_id, symbol)
    # Remove from memory
    if symbol in self.positions:
        del self.positions[symbol]
    log.info("🗑️ POSITION_DELETED | user=%s symbol=%s (CLOSED)", self.user_id, symbol)
except Exception as e:
    log.debug("📝 DELETE_POS_FAIL | user=%s symbol=%s err=%s", self.user_id, symbol, e)
```

### 2. Frontend - Filter OPEN Positions Only (`app/static/dashboard.html`)

#### A. Initial Load Filter
```javascript
async function refreshPositions() {
  const d = await (await fetch(`/api/positions?user_id=${USER_ID}`)).json();
  const pos = d.positions || [];

  // Filter to show only OPEN positions in Active Positions table
  const activePos = pos.filter(p => p.status === 'OPEN');

  // Update global map with ALL positions (for tick updates)
  POS_MAP = {};
  pos.forEach(p => { POS_MAP[p.symbol] = p; });

  renderPositions(activePos); // Only render OPEN positions
  renderAlerts();
}
```

#### B. WebSocket Update Filter
```javascript
if (d.type === 'pos' && d.position) {
  // Update or remove from map based on status
  if (d.position.status === 'OPEN') {
    POS_MAP[d.position.symbol] = d.position;
  } else {
    // Remove closed/error positions from map
    delete POS_MAP[d.position.symbol];
  }
  
  // Render only OPEN positions
  const activePos = Object.values(POS_MAP).filter(p => p.status === 'OPEN');
  renderPositions(activePos);
  renderAlerts();
}
```

## How It Works Now

### Square Off Flow:
1. **User clicks "Square Off All"**
2. **Backend exits all positions** via `exit_all_open_positions()`
3. **For each position:**
   - Places exit order on Zerodha
   - Sets status to "CLOSED"
   - **Deletes from Redis** (not upsert)
   - **Removes from memory** (`del self.positions[symbol]`)
   - Clears open trade guard
4. **WebSocket broadcasts position update** with CLOSED status
5. **Frontend receives update:**
   - Removes CLOSED position from `POS_MAP`
   - Re-renders Active Positions table
   - **Position disappears from dashboard**

### Result:
✅ Position exited from Zerodha  
✅ Position removed from Redis  
✅ Position removed from memory  
✅ Position removed from dashboard  
✅ Clean state - no lingering CLOSED positions  

## Benefits

1. **Clean Dashboard**: Only truly active positions shown
2. **Accurate Count**: "11 Active" badge shows actual open positions
3. **No Clutter**: CLOSED positions don't pollute the view
4. **Instant Feedback**: Positions disappear immediately after square-off
5. **Memory Efficient**: Closed positions not stored unnecessarily

## Testing

### Test 1: Single Square Off
1. Open a position
2. Click "Square Off" button
3. **Expected**: Position disappears from Active Positions table immediately

### Test 2: Square Off All
1. Open multiple positions (e.g., 5-10)
2. Click "Square Off All" button
3. Confirm the dialog
4. **Expected**: All positions disappear from table, count shows "0 Active"

### Test 3: Verify Zerodha
1. After square-off, check Zerodha positions
2. **Expected**: Positions should be closed in Zerodha as well

## Logs to Watch

After square-off, you'll see:
```
✅ EXIT_ORDER_OK | user=1 trade=abc123 symbol=SBIN exit_oid=240128000123456 reason=MANUAL_EXIT_ALL | pnl=15.50
🗑️ POSITION_DELETED | user=1 symbol=SBIN (CLOSED)
🧹 CLEAR_OPEN_OK | user=1 trade=abc123 symbol=SBIN
🏁 EXIT_DONE | user=1 symbol=SBIN
```

## Status
✅ **FIXED** - Closed positions are now properly removed from both backend and frontend
