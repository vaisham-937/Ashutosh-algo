# Dashboard Alert Display Fix - Summary

## Issues Fixed

### 1. **Missing `safeId()` Function** ✅
**Problem**: The WebSocket message handler was calling `safeId(s)` on line 1200, but this function didn't exist, causing JavaScript errors that prevented live updates.

**Solution**: Added the `safeId()` helper function:
```javascript
function safeId(symbol) {
  return (symbol || '').replace(/[^a-zA-Z0-9]/g, '_');
}
```

### 2. **Race Condition in Alert Storage** ✅
**Problem**: The backend was broadcasting alerts to the UI *before* saving them to Redis. When the UI received the WebSocket message and immediately refetched the alert list, the new alert wasn't in the database yet.

**Solution**: Reordered the operations in `app/main.py`:
```python
# Store alert history FIRST so it's ready when UI refetches
await store.save_alert(user_id, alert_data)

# Push to UI (which triggers reload)
await ws_mgr.broadcast(user_id, alert_data)
```

### 3. **Timestamp Format Issues** ✅
**Problem**: Inconsistent timestamp formats between backend and frontend caused parsing issues.

**Solution**: 
- Backend now uses ISO 8601 format with 'T' separator: `2026-01-28T13:22:24`
- Frontend improved to handle `Date.parse()` correctly
- Added fallback to current IST time if Chartink doesn't provide timestamp

### 4. **Element ID Consistency** ✅
**Problem**: Alert table was using raw symbol names as element IDs (e.g., `altp-SBIN`), but symbols with special characters (like `M&M`) would create invalid IDs.

**Solution**: Both rendering and WebSocket updates now use `safeId()` to sanitize symbols for HTML IDs.

## How It Works Now

1. **Chartink sends webhook** → Backend receives alert
2. **Backend saves to Redis** → Alert is persisted immediately
3. **Backend broadcasts to WebSocket** → UI receives notification
4. **UI refetches alert list** → Gets complete data including the new alert
5. **UI renders alerts** → Displays with proper timestamps and IDs
6. **Live ticks update** → WebSocket updates LTP, % change, and TSL values in real-time

## Testing

1. Send a test webhook from Chartink
2. Alert should appear immediately on dashboard
3. Time should show exact Chartink trigger time (IST)
4. Live price updates should work for all symbols
5. Dashboard auto-refreshes when new alerts arrive

## Files Modified

- `app/chartink_client.py` - Timestamp format and fallback
- `app/main.py` - Alert storage order fix
- `app/static/dashboard.html` - Added `safeId()` function and fixed element IDs
