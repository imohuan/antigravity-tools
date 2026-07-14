"""每日聚合统计 — 直接从 SQLite 聚合表读取

数据在 LogStore.insert() 时实时写入聚合表，无需定时同步。
"""

import logging
from .log_store import LogStore

logger = logging.getLogger(__name__)


class DailyStatsManager:
    """每日统计管理器"""

    def __init__(self, log_store: LogStore):
        self._log_store = log_store

    def get_all(self) -> dict:
        """获取所有日统计 — 兼容旧接口，返回空（数据在聚合表中）"""
        return {}

    def get_calendar(self, months: int = 4) -> list[dict]:
        """获取日历热力图数据 — 从聚合表查，自动补全缺失日期为 0

        返回最近 N 个月的完整日期序列，没有记录的日期也包含（credits=0, count=0）。
        这样前端日历和折线图能正确显示"无消耗"日期，不会出现位置缺失。
        """
        import datetime as dt
        today = dt.date.today()
        # 计算起始日期：months 个月的 1 号
        start_year = today.year
        start_month = today.month - months + 1
        while start_month <= 0:
            start_month += 12
            start_year -= 1
        start_date = dt.date(start_year, start_month, 1)

        # 从数据库查询
        rows = self._log_store.conn.execute(
            "SELECT date, credits, requests FROM daily_stats "
            "WHERE date >= ? AND date <= ? ORDER BY date",
            (start_date.isoformat(), today.isoformat()),
        ).fetchall()
        # 索引化
        existing = {r[0]: (round(r[1], 4), r[2]) for r in rows}

        # 逐日补全
        out = []
        d = start_date
        while d <= today:
            key = d.isoformat()
            if key in existing:
                credits, count = existing[key]
            else:
                credits, count = 0.0, 0
            out.append({"date": key, "credits": credits, "count": count})
            d += dt.timedelta(days=1)
        return out

    def get_overview(self) -> dict:
        """获取全局总览 — 从聚合表查"""
        row = self._log_store.conn.execute(
            "SELECT COALESCE(SUM(requests),0), COALESCE(SUM(success),0), COALESCE(SUM(failed),0), "
            "COALESCE(SUM(tokens),0), COALESCE(SUM(credits),0), "
            "CASE WHEN SUM(requests)>0 THEN CAST(SUM(duration_sum) AS REAL)/SUM(requests) ELSE 0 END "
            "FROM daily_stats"
        ).fetchone()

        total_requests = row[0]
        total_success = row[1]
        total_failed = row[2]
        total_tokens = row[3]
        total_credits = round(row[4], 4)
        avg_duration_ms = int(row[5])

        success_rate = round(total_success / total_requests * 100, 1) if total_requests > 0 else 0

        model_rows = self._log_store.conn.execute(
            "SELECT model, SUM(count) as cnt, SUM(credits) as credits "
            "FROM daily_model_stats GROUP BY model ORDER BY credits DESC LIMIT 10"
        ).fetchall()

        key_rows = self._log_store.conn.execute(
            "SELECT key_label, SUM(count) as cnt, SUM(credits) as credits "
            "FROM daily_key_stats GROUP BY key_label ORDER BY credits DESC LIMIT 10"
        ).fetchall()

        return {
            "total_requests": total_requests,
            "total_success": total_success,
            "total_failed": total_failed,
            "success_rate": success_rate,
            "total_tokens": total_tokens,
            "total_credits": total_credits,
            "avg_duration_ms": avg_duration_ms,
            "by_model": [
                {"name": r[0] or "unknown", "credits": round(r[2], 4), "count": r[1]}
                for r in model_rows
            ],
            "by_key": [
                {"name": r[0] or "unknown", "credits": round(r[2], 4), "count": r[1]}
                for r in key_rows
            ],
        }
