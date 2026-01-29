# Alert History Management - Clear All Feature ✅

## What Was Added

A new "**Clear All**" button to delete all alert history from Redis directly from the dashboard.

---

## Features

### 1. Backend API Endpoint (`app/main.py`)

```python
@app.delete("/api/alerts")
async def delete_all_alerts(user_id: int = 1) -> Dict[str, Any]:
    """Clear all alert history for a user"""
    user_id = int(user_id)
    try:
        await store.r.delete(f"alerts:{user_id}")
        return {"status": "ok", "message": "All alerts cleared"}
    except Exception as e:
        return {"error": str(e)}
```

### 2. Frontend Button (`app/static/dashboard.html`)

Located in the "Live Signals" section, next to the Refresh button:

```html
<button onclick="clearAllAlerts()" 
  class="btn px-3 py-1.5 text-xs bg-rose-500/10 text-rose-400 border border-rose-500/20">
  <svg>...</svg> <!-- Trash icon -->
  Clear All
</button>
```

### 3. JavaScript Function

```javascript
async function clearAllAlerts() {
  if (!confirm("⚠️ Delete ALL alert history? This cannot be undone.")) return;
  try {
    const r = await fetch(`/api/alerts?user_id=${USER_ID}`, {
      method: "DELETE"
    });
    const d = await r.json();
    if (d.error) throw d.error;
    toast("All alerts cleared successfully");
    loadAlerts(); // Refresh to show empty table
  } catch (e) { toast(e, 'error'); }
}
```

---

## How to Use

### From Dashboard:

1. Navigate to the "**Live Signals**" section
2. Click the "**Clear All**" button (red trash icon)
3. Confirm the action in the dialog
4. ✅ All alerts are deleted from Redis
5. Table refreshes to show empty state

### Safety Features:

✅ **Confirmation Dialog** - Prevents accidental clicks  
✅ **Error Handling** - Shows toast notification if deletion fails  
✅ **Auto Refresh** - Table updates immediately after deletion  
✅ **Visual Feedback** - Toast notification on success  

---

## Alternative Methods

### 1. Using Redis CLI (Manual)

```bash
redis-cli
DEL alerts:1
exit
```

### 2. Using Python Script

```python
import asyncio
import redis.asyncio as redis

async def clear():
    r = await redis.from_url("redis://localhost:6379/0")
    await r.delete("alerts:1")
    await r.close()

asyncio.run(clear())
```

### 3. Keep Last N Alerts (Trim)

```bash
redis-cli
LTRIM alerts:1 0 49  # Keep last 50
```

---

## Built-in Auto-Cleanup

The system already has automatic cleanup:

```python
# In redis_store.py
await self.r.ltrim(k, 0, 199)  # Keep only last 200 alerts
await self.r.expire(k, seconds_until_next_ist_day())  # Expire daily
```

So alerts are automatically managed:
- ✅ Only last 200 kept
- ✅ Expire after midnight IST + 6 hours

---

## Use Cases

### When to Clear Alerts:

1. **Testing** - Clear old test data
2. **New Trading Day** - Start fresh with clean history
3. **Performance** - Too many alerts slowing down UI
4. **Privacy** - Remove trading history
5. **Debugging** - Clear data between tests

### When NOT to Clear:

1. During active trading (unless intentional)
2. Before reviewing performance metrics
3. If alerts contain valuable analysis data

---

## What Gets Deleted

✅ All alert records from Redis  
✅ Live Signals table becomes empty  
✅ Alert count shows "0 Alerts"  

### What DOES NOT Get Deleted:

❌ Alert Configurations (settings remain)  
❌ Active Positions (trades stay open)  
❌ Broker credentials  
❌ Auto square-off settings  

---

## Status

✅ **Fully Functional** - Clear All button is now active on the dashboard!

The server will auto-reload with these changes. **Refresh your dashboard** to see the new "Clear All" button in the Live Signals section.
