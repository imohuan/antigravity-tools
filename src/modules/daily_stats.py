"""每日聚合统计 — 独立 daily_stats.json 持久化

每天一行聚合数据，永久保留。文件极小（365 天 ~几十 KB）。
"""

import json
import logging
import os
from collections import defaultdict
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
        """获取日历热力图数据"""
        stats = self._load()
        result = []
        for date_key, day in sorted(stats.items()):
            result.append({
                "date": date_key,
                "credits": day.get("total_credits", 0),
                "count": day.get("request_count", 0),
            })
        return result[-(months * 31):]

    def get_overview(self) -> dict:
        """获取全局总览"""
        stats = self._load()

        total_requests = 0
        total_success = 0
        total_failed = 0
        total_tokens = 0
        total_credits = 0.0
        total_duration = 0

        by_model = defaultdict(lambda: {"credits": 0.0, "count": 0})
        by_key = defaultdict(lambda: {"credits": 0.0, "count": 0})

        for day in stats.values():
            total_requests += day.get("request_count", 0)
            total_success += day.get("success_count", 0)
            total_failed += day.get("failed_count", 0)
            total_tokens += day.get("total_tokens", 0)
            total_credits += day.get("total_credits", 0)
            total_duration += day.get("avg_duration_ms", 0) * day.get(
                "request_count", 0
            )

            for model, data in (day.get("by_model") or {}).items():
                by_model[model]["credits"] = round(
                    by_model[model]["credits"] + data["credits"], 4
                )
                by_model[model]["count"] += data["count"]

            for key, data in (day.get("by_key") or {}).items():
                by_key[key]["credits"] = round(
                    by_key[key]["credits"] + data["credits"], 4
                )
                by_key[key]["count"] += data["count"]

        avg_duration = (
            int(total_duration / total_requests) if total_requests > 0 else 0
        )
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
            "total_tokens": total_tokens,
            "total_credits": round(total_credits, 4),
            "avg_duration_ms": avg_duration,
            "by_model": [
                {"name": k, "credits": v["credits"], "count": v["count"]}
                for k, v in top_models
            ],
            "by_key": [
                {"name": k, "credits": v["credits"], "count": v["count"]}
                for k, v in top_keys
            ],
        }
