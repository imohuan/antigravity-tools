"""每日聚合统计 — 独立 daily_stats.json 持久化

每天一行聚合数据，永久保留。文件极小（365 天 ~几十 KB）。
"""

import json
import logging
import os
from datetime import datetime

from .log_store import LogStore

logger = logging.getLogger(__name__)


class DailyStatsManager:
    """每日统计管理器"""

    def __init__(self, stats_path: str, log_store: LogStore):
        self._path = stats_path
        self._log_store = log_store

    def _load(self) -> dict:
        if not os.path.exists(self._path):
            return {}
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return json.loads(f.read() or "{}")
        except Exception:
            return {}

    def _save(self, data: dict):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except Exception as e:
            logger.error(f"[DailyStats] 写入失败: {e}")
            try:
                os.remove(tmp)
            except Exception:
                pass

    def sync_today(self):
        """从 SQLite 聚合今天的数据并持久化"""
        today = datetime.now().strftime("%Y-%m-%d")

        overview = self._log_store.aggregate_today()
        if not overview:
            return

        by_model = self._log_store.get_model_distribution(today)
        by_key = self._log_store.get_key_distribution(today)

        day_entry = {**overview, "by_model": by_model, "by_key": by_key}

        stats = self._load()
        stats[today] = day_entry
        self._save(stats)

        logger.info(
            f"[DailyStats] {today}: {overview['request_count']} 请求, "
            f"{overview['total_credits']} 积分"
        )

    def get_all(self) -> dict:
        return self._load()

    def get_calendar(self, months: int = 4) -> list[dict]:
        """获取日历热力图数据 — 实时从 SQLite 聚合"""
        return self._log_store.aggregate_calendar(months)

    def get_overview(self) -> dict:
        """获取全局总览 — 实时从 SQLite 聚合，不依赖 daily_stats.json 定时同步"""
        agg = self._log_store.aggregate_all()
        if not agg:
            return {
                "total_requests": 0,
                "total_success": 0,
                "total_failed": 0,
                "success_rate": 0,
                "total_tokens": 0,
                "total_credits": 0,
                "avg_duration_ms": 0,
                "by_model": [],
                "by_key": [],
            }

        total_requests = agg["request_count"]
        total_success = agg["success_count"]
        total_failed = agg["failed_count"]

        # 模型和 Key 分布只在数据量较小时实时查，大量数据时跳过避免卡顿
        by_model = {}
        by_key = {}
        if total_requests <= 50000:
            by_model = self._log_store.get_all_model_distribution()
            by_key = self._log_store.get_all_key_distribution()

        success_rate = (
            round(total_success / total_requests * 100, 1)
            if total_requests > 0
            else 0
        )

        top_models = sorted(
            by_model.items(), key=lambda x: x[1]["credits"], reverse=True
        )[:10]
        top_keys = sorted(
            by_key.items(), key=lambda x: x[1]["credits"], reverse=True
        )[:10]

        return {
            "total_requests": total_requests,
            "total_success": total_success,
            "total_failed": total_failed,
            "success_rate": success_rate,
            "total_tokens": agg["total_tokens"],
            "total_credits": agg["total_credits"],
            "avg_duration_ms": agg["avg_duration_ms"],
            "by_model": [
                {"name": k, "credits": v["credits"], "count": v["count"]}
                for k, v in top_models
            ],
            "by_key": [
                {"name": k, "credits": v["credits"], "count": v["count"]}
                for k, v in top_keys
            ],
        }