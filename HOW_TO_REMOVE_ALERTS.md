# How to Remove Alerts from Redis

## Overview
Alerts are stored in Redis as a list. Here are different methods to manage and delete them.

---

## Method 1: Clear ALL Alerts for a User (Using Redis CLI)

### Step 1: Connect to Redis
```bash
redis-cli
```

### Step 2: Delete Alert History
```redis
# Delete all alerts for user 1
DEL alerts:1

# Or if using different user ID
DEL alerts:<USER_ID>
```

### Step 3: Verify Deletion
```redis
LLEN alerts:1
# Should return 0
```

---

## Method 2: Clear Specific Number of Alerts (Keep Recent)

### Keep Last 10 Alerts Only:
```redis
# Trim to keep only last 10 alerts
LTRIM alerts:1 0 9
```

### Keep Last 50 Alerts Only:
```redis
LTRIM alerts:1 0 49
```

---

## Method 3: View Alert Count Before Deleting

```redis
# Check how many alerts are stored
LLEN alerts:1

# View all alerts (WARNING: could be many)
LRANGE alerts:1 0 -1

# View first 10 alerts
LRANGE alerts:1 0 9

# View last 10 alerts
LRANGE alerts:1 -10 -1
```

---

## Method 4: Add API Endpoint to Delete Alerts

If you want to add a button on the dashboard to clear alerts, add this to `app/main.py`:

### Backend API Endpoint:
```python
@app.delete("/api/alerts")
async def delete_alerts(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Clear all alert history"""
    user_id = int(payload.get("user_id", 1))
    
    try:
        # Delete all alerts for this user
        await store.r.delete(f"alerts:{user_id}")
        return {"status": "ok", "message": "All alerts cleared"}
    except Exception as e:
        return {"error": str(e)}
```

### Or to Keep Last N Alerts:
```python
@app.post("/api/alerts/trim")
async def trim_alerts(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only last N alerts"""
    user_id = int(payload.get("user_id", 1))
    keep = int(payload.get("keep", 50))  # Default keep last 50
    
    try:
        # Trim to keep only last N alerts
        await store.r.ltrim(f"alerts:{user_id}", 0, keep - 1)
        remaining = await store.r.llen(f"alerts:{user_id}")
        return {"status": "ok", "kept": remaining}
    except Exception as e:
        return {"error": str(e)}
```

### Frontend Dashboard Button (HTML):
```html
<!-- Add this button in dashboard.html -->
<button onclick="clearAlerts()" 
  class="btn btn-danger px-3 py-1.5 text-xs">
  Clear All Alerts
</button>

<script>
async function clearAlerts() {
  if (!confirm("⚠️ Delete ALL alert history? This cannot be undone.")) return;
  
  try {
    const r = await fetch("/api/alerts", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: USER_ID })
    });
    const d = await r.json();
    if (d.error) throw d.error;
    
    toast("All alerts cleared");
    loadAlerts(); // Refresh the table
  } catch (e) {
    toast(e, 'error');
  }
}
</script>
```

---

## Method 5: Automatic Cleanup (Recommended)

The system already has automatic cleanup configured:

```python
# In redis_store.py - save_alert method
await self.r.lpush(k, json.dumps(alert_data))
await self.r.ltrim(k, 0, 199)  # Keep only last 200 alerts
await self.r.expire(k, seconds_until_next_ist_day())  # Expire daily
```

This means:
- ✅ Only last 200 alerts are kept automatically
- ✅ Alerts expire after midnight IST (+ 6 hours grace)

---

## Method 6: Using Python Script

Create a file `clear_alerts.py`:

```python
# clear_alerts.py
import asyncio
import redis.asyncio as redis

async def clear_alerts(user_id: int = 1):
    r = await redis.from_url("redis://localhost:6379/0")
    
    # Delete all alerts
    await r.delete(f"alerts:{user_id}")
    
    # Or trim to keep last 10
    # await r.ltrim(f"alerts:{user_id}", 0, 9)
    
    print(f"Alerts cleared for user {user_id}")
    await r.close()

if __name__ == "__main__":
    asyncio.run(clear_alerts(user_id=1))
```

Run:
```bash
python clear_alerts.py
```

---

## Method 7: Clear All Redis Data (NUCLEAR OPTION ⚠️)

**WARNING**: This deletes EVERYTHING from Redis!

```bash
redis-cli FLUSHDB
```

This will delete:
- All alerts
- All positions
- All credentials
- All configurations
- Everything!

**Only use if you want a complete reset!**

---

## Common Redis Commands Reference

```redis
# List all keys
KEYS *

# Delete specific key
DEL alerts:1

# Check key type
TYPE alerts:1

# Get list length
LLEN alerts:1

# View all alerts
LRANGE alerts:1 0 -1

# Trim list (keep first 50)
LTRIM alerts:1 0 49

# Delete last N items (remove oldest)
# (Use LTRIM to keep newest instead)

# Check if key exists
EXISTS alerts:1

# See when key expires
TTL alerts:1
```

---

## Recommended Approach

**For Production:**
1. Use the automatic cleanup (already in place - keeps last 200)
2. Add a "Clear Alerts" button on dashboard (Method 4)
3. Set appropriate daily expiry (already configured)

**For Development/Testing:**
1. Use Redis CLI to quickly clear: `DEL alerts:1`
2. Or trim to specific count: `LTRIM alerts:1 0 9`

**For Debugging:**
1. Check count first: `LLEN alerts:1`
2. View recent alerts: `LRANGE alerts:1 0 9`
3. Then delete if needed

---

## Key Structure

```
alerts:{user_id}  (Redis LIST)
├── alert 1 (newest) - index 0
├── alert 2
├── alert 3
├── ...
└── alert 200 (oldest) - index 199

Auto-trimmed to 200 items
Expires daily at midnight IST + 6 hours
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Delete all alerts | `DEL alerts:1` |
| Keep last 10 | `LTRIM alerts:1 0 9` |
| Keep last 50 | `LTRIM alerts:1 0 49` |
| View count | `LLEN alerts:1` |
| View last 10 | `LRANGE alerts:1 0 9` |
| Check if exists | `EXISTS alerts:1` |

---

## Summary

**Easiest Way**: Open Redis CLI and run:
```bash
redis-cli
DEL alerts:1
exit
```

**Dashboard Way**: Add the API endpoint and button (Method 4)

**Already Configured**: System keeps last 200 alerts and expires them daily automatically ✅
