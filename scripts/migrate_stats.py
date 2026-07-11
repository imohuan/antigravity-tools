"""一次性脚本: 从 request_logs 明细表反算聚合表"""
import sqlite3, os

db_path = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")),
    ".antigravity-tools", "request_logs.db"
)

if not os.path.exists(db_path):
    print(f"数据库不存在: {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
conn.execute("PRAGMA journal_mode=WAL")

# 清空旧聚合数据
conn.execute("DELETE FROM daily_stats")
conn.execute("DELETE FROM daily_model_stats")
conn.execute("DELETE FROM daily_key_stats")

# 从明细表反算 daily_stats
conn.execute("""
    INSERT INTO daily_stats (date, requests, success, failed, tokens, credits, duration_sum)
    SELECT date, COUNT(*),
        SUM(CASE WHEN status='success' THEN 1 ELSE 0 END),
        SUM(CASE WHEN status!='success' THEN 1 ELSE 0 END),
        COALESCE(SUM(total_tokens), 0), COALESCE(SUM(credit), 0),
        COALESCE(SUM(duration_ms), 0)
    FROM request_logs GROUP BY date
""")

# 从明细表反算 daily_model_stats
conn.execute("""
    INSERT INTO daily_model_stats (date, model, count, credits)
    SELECT date, COALESCE(NULLIF(model,''),'unknown'),
        COUNT(*), COALESCE(SUM(credit), 0)
    FROM request_logs WHERE credit > 0
    GROUP BY date, COALESCE(NULLIF(model,''),'unknown')
""")

# 从明细表反算 daily_key_stats
conn.execute("""
    INSERT INTO daily_key_stats (date, key_label, count, credits)
    SELECT date, COALESCE(NULLIF(main_key_label,''),'unknown'),
        COUNT(*), COALESCE(SUM(credit), 0)
    FROM request_logs WHERE credit > 0
    GROUP BY date, COALESCE(NULLIF(main_key_label,''),'unknown')
""")

conn.commit()
print("迁移完成!")
for t in ["daily_stats", "daily_model_stats", "daily_key_stats"]:
    n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t}: {n} 行")
conn.close()
