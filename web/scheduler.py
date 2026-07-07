"""Background scheduler for periodic tasks.

- Daily quota sync at 08:00
"""

import logging
import sys
from pathlib import Path

# Ensure project root in sys.path so `from src.xxx` works
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger("antigravity.scheduler")

_scheduler: BackgroundScheduler | None = None


def _sync_all_quotas():
    """Fetch and persist quota for all configured accounts."""
    # Late import to avoid circular dependency at module level
    from web.api.quota import query_all_quotas

    try:
        result = query_all_quotas()
        logger.info(
            "Quota sync done: %d accounts, remaining=%s, total=%s",
            result.get("account_count", 0),
            result.get("total_remaining", 0),
            result.get("total_credits", 0),
        )
    except Exception as e:
        logger.error("Quota sync failed: %s", e)


def start_scheduler() -> BackgroundScheduler:
    """Create and start the background scheduler.

    Called once during server startup (after init_db).
    """
    global _scheduler

    _scheduler = BackgroundScheduler(
        timezone="Asia/Shanghai",
        job_defaults={"misfire_grace_time": 300},  # 5 min grace for missed runs
    )

    _scheduler.add_job(
        _sync_all_quotas,
        trigger="cron",
        hour=8,
        minute=0,
        id="daily_quota_sync",
        name="Daily Quota Sync",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Scheduler started — quota sync every day at 08:00 (CST)")
    return _scheduler


def shutdown_scheduler():
    """Gracefully stop the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
