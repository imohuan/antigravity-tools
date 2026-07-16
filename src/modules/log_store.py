"""SQLite 请求日志存储 — 只追加写入，支持聚合查询和定期清理

替代旧的 JSON 全量日志方案：
- 写入：INSERT 一行，几毫秒
- 查询：SQL GROUP BY，秒出
- 清理：自动删除 30 天前数据
- WAL 模式：读写并发，不阻塞
"""

import logging
import os
import sqlite3
import time
from datetime import datetime

logger = logging.getLogger(__name__)

RETAIN_DAYS = 30


class LogStore:
    """SQLite 请求日志存储"""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-8000")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS request_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    date TEXT NOT NULL,
                    hour INTEGER NOT NULL DEFAULT 0,
                    main_key_id TEXT DEFAULT '',
                    main_key_label TEXT DEFAULT '',
                    model TEXT DEFAULT '',
                    status TEXT DEFAULT '',
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    credit REAL DEFAULT 0.0,
                    duration_ms INTEGER DEFAULT 0,
                    request_path TEXT DEFAULT ''
                )
            """)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_logs_date ON request_logs(date)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_logs_model ON request_logs(model)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_logs_key ON request_logs(main_key_id)"
            )
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_stats (
                    date TEXT PRIMARY KEY,
                    requests INTEGER DEFAULT 0,
                    success INTEGER DEFAULT 0,
                    failed INTEGER DEFAULT 0,
                    tokens INTEGER DEFAULT 0,
                    credits REAL DEFAULT 0.0,
                    duration_sum INTEGER DEFAULT 0
                )
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_model_stats (
                    date TEXT NOT NULL,
                    model TEXT NOT NULL,
                    count INTEGER DEFAULT 0,
                    credits REAL DEFAULT 0.0,
                    PRIMARY KEY (date, model)
                )
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_key_stats (
                    date TEXT NOT NULL,
                    key_label TEXT NOT NULL,
                    count INTEGER DEFAULT 0,
                    credits REAL DEFAULT 0.0,
                    PRIMARY KEY (date, key_label)
                )
            """)

            # 补全前端需要的字段（兼容旧数据库）
            for col, col_type in [
                ("key_mode", "TEXT DEFAULT ''"),
                ("error", "TEXT DEFAULT ''"),
                ("first_token_ms", "INTEGER DEFAULT 0"),
                ("attempt", "INTEGER DEFAULT 1"),
            ]:
                try:
                    self._conn.execute(f"ALTER TABLE request_logs ADD COLUMN {col} {col_type}")
                except sqlite3.OperationalError:
                    pass

            self._conn.commit()
        return self._conn

    def insert(self, log: dict):
        """插入一条日志"""
        ts = log.get("timestamp", time.time())
        event = log.get("event", "")
        # 根据 event 推导 status：只有 end 才是 success，其余（request/error/auth_fail/upstream_error 等）都是 failed
        status = log.get("status", "")
        if not status:
            status = "success" if event == "end" else ("failed" if event else "success")
        # 计算 total_tokens
        prompt_tokens = log.get("prompt_tokens", 0)
        completion_tokens = log.get("completion_tokens", 0)
        total_tokens = log.get("total_tokens", 0) or (prompt_tokens + completion_tokens)
        try:
            self.conn.execute(
                """INSERT INTO request_logs
                   (timestamp, date, hour, main_key_id, main_key_label, model,
                    status, prompt_tokens, completion_tokens, total_tokens,
                    credit, duration_ms, request_path,
                    key_mode, error, first_token_ms, attempt)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ts,
                    datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
                    datetime.fromtimestamp(ts).hour,
                    log.get("main_key_id", ""),
                    log.get("main_key_label", ""),
                    log.get("model", ""),
                    status,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    log.get("credit", 0.0),
                    log.get("duration_ms", 0),
                    log.get("request_path", ""),
                    log.get("key_mode", ""),
                    log.get("error", ""),
                    log.get("first_token_ms", 0),
                    log.get("attempt", 1),
                ),
            )

            # INSERT 明细后，立即 UPSERT 三张聚合表
            date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            model = log.get("model", "") or "unknown"
            key_label = log.get("main_key_label", "") or "unknown"
            status = log.get("status", "success")
            is_success = 1 if status == "success" else 0
            is_failed = 0 if status == "success" else 1
            credit = log.get("credit", 0.0) or 0.0
            tokens = log.get("total_tokens", 0) or 0
            duration = log.get("duration_ms", 0) or 0

            self.conn.execute("""
                INSERT INTO daily_stats (date, requests, success, failed, tokens, credits, duration_sum)
                VALUES (?, 1, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    requests = requests + 1,
                    success = success + ?,
                    failed = failed + ?,
                    tokens = tokens + ?,
                    credits = credits + ?,
                    duration_sum = duration_sum + ?
            """, (date_str, is_success, is_failed, tokens, credit, duration,
                  is_success, is_failed, tokens, credit, duration))

            self.conn.execute("""
                INSERT INTO daily_model_stats (date, model, count, credits)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(date, model) DO UPDATE SET
                    count = count + 1,
                    credits = credits + ?
            """, (date_str, model, credit, credit))

            self.conn.execute("""
                INSERT INTO daily_key_stats (date, key_label, count, credits)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(date, key_label) DO UPDATE SET
                    count = count + 1,
                    credits = credits + ?
            """, (date_str, key_label, credit, credit))

            self.conn.commit()
        except Exception as e:
            logger.error(f"[LogStore] 写入日志失败: {e}")

    def aggregate_today(self) -> dict:
        """聚合今天的统计数据"""
        today = datetime.now().strftime("%Y-%m-%d")
        row = self.conn.execute(
            """SELECT
                 COUNT(*) as total,
                 SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success,
                 SUM(CASE WHEN status!='success' THEN 1 ELSE 0 END) as failed,
                 COALESCE(SUM(total_tokens), 0) as total_tokens,
                 COALESCE(SUM(credit), 0) as total_credits,
                 COALESCE(AVG(duration_ms), 0) as avg_duration_ms
               FROM request_logs WHERE date=?""",
            (today,),
        ).fetchone()
        if not row or row[0] == 0:
            return {}
        return {
            "date": today,
            "request_count": row[0],
            "success_count": row[1],
            "failed_count": row[2],
            "total_tokens": int(row[3]),
            "total_credits": round(row[4], 4),
            "avg_duration_ms": int(row[5]),
        }

    def aggregate_date(self, date_str: str) -> dict:
        """聚合指定日期的统计数据"""
        row = self.conn.execute(
            """SELECT
                 COUNT(*) as total,
                 SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success,
                 SUM(CASE WHEN status!='success' THEN 1 ELSE 0 END) as failed,
                 COALESCE(SUM(total_tokens), 0) as total_tokens,
                 COALESCE(SUM(credit), 0) as total_credits,
                 COALESCE(AVG(duration_ms), 0) as avg_duration_ms
               FROM request_logs WHERE date=?""",
            (date_str,),
        ).fetchone()
        if not row or row[0] == 0:
            return {}
        return {
            "date": date_str,
            "request_count": row[0],
            "success_count": row[1],
            "failed_count": row[2],
            "total_tokens": int(row[3]),
            "total_credits": round(row[4], 4),
            "avg_duration_ms": int(row[5]),
        }

    
    def aggregate_all(self) -> dict:
        """聚合所有日期的全局统计（实时查询 SQLite，不依赖 daily_stats.json）"""
        row = self.conn.execute(
            """SELECT
                 COUNT(*) as total,
                 SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success,
                 SUM(CASE WHEN status!='success' THEN 1 ELSE 0 END) as failed,
                 COALESCE(SUM(total_tokens), 0) as total_tokens,
                 COALESCE(SUM(credit), 0) as total_credits,
                 COALESCE(AVG(duration_ms), 0) as avg_duration_ms
               FROM request_logs"""
        ).fetchone()
        if not row or row[0] == 0:
            return {}
        return {
            "request_count": row[0],
            "success_count": row[1],
            "failed_count": row[2],
            "total_tokens": int(row[3]),
            "total_credits": round(row[4], 4),
            "avg_duration_ms": int(row[5]),
        }

    def aggregate_calendar(self, months: int = 4) -> list[dict]:
        rows = self.conn.execute(
            """SELECT date,
                 COUNT(*) as total,
                 COALESCE(SUM(credit), 0) as total_credits
               FROM request_logs
               WHERE date >= date('now', ?)
               GROUP BY date ORDER BY date""",
            (f"-{months} months",),
        ).fetchall()
        return [
            {"date": row[0], "credits": round(row[2], 4), "count": row[1]}
            for row in rows
        ]

    def get_all_model_distribution(self) -> dict:
        """获取所有日期的模型分布"""
        rows = self.conn.execute(
            """SELECT model, SUM(credit) as credits, COUNT(*) as cnt
               FROM request_logs WHERE credit > 0
               GROUP BY model ORDER BY credits DESC"""
        ).fetchall()
        return {
            (row[0] or "unknown"): {"credits": round(row[1], 4), "count": row[2]}
            for row in rows
        }

    def get_all_key_distribution(self) -> dict:
        """获取所有日期的 Key 分布"""
        rows = self.conn.execute(
            """SELECT main_key_label, SUM(credit) as credits, COUNT(*) as cnt
               FROM request_logs WHERE credit > 0
               GROUP BY main_key_label ORDER BY credits DESC"""
        ).fetchall()
        return {
            (row[0] or "unknown"): {"credits": round(row[1], 4), "count": row[2]}
            for row in rows
        }

    def get_model_distribution(self, date_str: str) -> dict:
        """获取指定日期按模型分布"""
        rows = self.conn.execute(
            """SELECT model, SUM(credit) as credits, COUNT(*) as cnt
               FROM request_logs WHERE date=? AND credit > 0
               GROUP BY model ORDER BY credits DESC""",
            (date_str,),
        ).fetchall()
        return {
            (row[0] or "unknown"): {"credits": round(row[1], 4), "count": row[2]}
            for row in rows
        }

    def get_key_distribution(self, date_str: str) -> dict:
        """获取指定日期按 Key 分布"""
        rows = self.conn.execute(
            """SELECT main_key_label, SUM(credit) as credits, COUNT(*) as cnt
               FROM request_logs WHERE date=? AND credit > 0
               GROUP BY main_key_label ORDER BY credits DESC""",
            (date_str,),
        ).fetchall()
        return {
            (row[0] or "unknown"): {"credits": round(row[1], 4), "count": row[2]}
            for row in rows
        }

    def cleanup_old(self):
        """清理超过保留期的日志"""
        cutoff = datetime.now().strftime("%Y-%m-%d")
        self.conn.execute(
            "DELETE FROM request_logs WHERE date < date(?, ?)",
            (cutoff, f"-{RETAIN_DAYS} days"),
        )
        self.conn.commit()

    def migrate_from_json(self, json_logs: list):
        """从旧的 JSON 日志迁移到 SQLite（一次性）"""
        if not json_logs:
            return 0
        count = 0
        for log in json_logs:
            try:
                self.insert(log)
                count += 1
            except Exception:
                pass
        logger.info(f"[LogStore] 从 JSON 迁移了 {count} 条日志到 SQLite")
        return count
