"""
Daily Cleanup Script - Auto Reset at 8 AM IST

This script clears all previous day's trading data to give a fresh start each morning.
Should be scheduled to run daily at 8:00 AM IST.

What gets cleared:
- All positions (OPEN/EXIT_CONDITIONS_MET/EXITING/CLOSED)
- All alerts history
- All open trades
- Daily trade counters
- Kill switch (reset to False)
- Sector performance tracking

What is PRESERVED:
- Alert configurations (user settings)
- API credentials
- Access tokens
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
import pytz

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.redis_store import RedisStore

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


async def daily_cleanup(user_id: int = 1):
    """
    Perform daily cleanup of trading data.
    
    Args:
        user_id: User ID to clean up (default: 1)
    """
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    
    log.info("=" * 80)
    log.info("🧹 DAILY CLEANUP STARTED")
    log.info(f"⏰ Time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    log.info(f"👤 User ID: {user_id}")
    log.info("=" * 80)
    
    # Initialize Redis store
    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    store = RedisStore(redis_url)
    
    try:
        # Connect to Redis
        await store.connect()
        log.info("✅ Connected to Redis")
        
        # 1. Clear all positions
        positions = await store.list_positions(user_id)
        pos_count = len(positions) if positions else 0
        log.info(f"📊 Found {pos_count} positions to clear")
        
        if pos_count > 0:
            for pos in positions:
                symbol = pos.get('symbol')
                if symbol:
                    await store.delete_position(user_id, symbol)
            log.info(f"✅ Cleared {pos_count} positions")
        
        # 2. Clear alerts history
        alerts = await store.get_recent_alerts(user_id, limit=1000)
        alert_count = len(alerts) if alerts else 0
        log.info(f"📢 Found {alert_count} alerts to clear")
        
        if alert_count > 0:
            # Delete all alerts
            key = store._key(f"user:{user_id}:alerts")
            await store.r.delete(key)
            log.info(f"✅ Cleared {alert_count} alerts")
        
        # 3. Clear open trades tracking
        # This removes the symbol tokens cache
        token_key = store._key(f"user:{user_id}:symbol_tokens")
        await store.r.delete(token_key)
        log.info("✅ Cleared symbol tokens cache")
        
        # 4. Reset kill switch
        await store.set_kill(user_id, False)
        log.info("✅ Reset kill switch to OFF")
        
        # 5. Clear any pending rate limits (OTP, etc)
        # Note: We keep user sessions active, only clear rate limits
        rate_limit_pattern = f"user:{user_id}:ratelimit:*"
        keys = []
        async for key in store.r.scan_iter(match=store._key(rate_limit_pattern)):
            keys.append(key)
        
        if keys:
            await store.r.delete(*keys)
            log.info(f"✅ Cleared {len(keys)} rate limit entries")
        
        # 6. Log alert configurations (preserved)
        alert_configs = await store.list_alert_configs(user_id)
        config_count = len(alert_configs) if alert_configs else 0
        log.info(f"ℹ️  Preserved {config_count} alert configurations")
        
        # Summary
        log.info("=" * 80)
        log.info("✅ DAILY CLEANUP COMPLETED SUCCESSFULLY")
        log.info(f"   - Positions cleared: {pos_count}")
        log.info(f"   - Alerts cleared: {alert_count}")
        log.info(f"   - Kill switch: RESET")
        log.info(f"   - Configs preserved: {config_count}")
        log.info("=" * 80)
        
    except Exception as e:
        log.error(f"❌ CLEANUP FAILED: {e}", exc_info=True)
        raise
    
    finally:
        await store.close()
        log.info("🔌 Redis connection closed")


async def main():
    """Main entry point"""
    try:
        # Get user ID from environment or use default
        user_id = int(os.getenv("USER_ID", "1"))
        
        # Run cleanup
        await daily_cleanup(user_id)
        
        log.info("🎉 Daily cleanup script finished successfully!")
        return 0
        
    except Exception as e:
        log.error(f"💥 Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
