# 项目约定

## 架构关系
- **upstream** (qinchangxv/antigravity-tools) = 核心引擎，所有优化都采纳
- **本地 fork** = 核心 + web 仪表盘/日志等插件功能
- 合并原则：上游优化照单全收，本地新功能寸步不让

## 合并文件分类
- **A 类（本地插件）**: web/, src/modules/log_store.py, src/modules/daily_stats.py, scripts/, docs/, dev/install 脚本, .codegraph/, .cursor/, .workbuddy/ — 合并后用 `git checkout HEAD --` 恢复
- **B 类（upstream 核心）**: src/ui/ 全部, main.py, main_window.py, updater.py, api_client.py, oauth.py, app.py, version.json, spec 文件, build.yml — 合并后用 `git checkout upstream/main --` 覆盖
- **C 类（手动合并）**: proxy_server.py, requirements.txt, .gitignore

## proxy_server.py 合并策略
以 upstream 为基底，植入：
1. LogStore/DailyStatsManager 导入
2. ProxyDatabase 新增 log_store/daily_stats lazy 属性
3. add_request_log → SQLite 日志
4. get_request_logs → 分页 SQLite 查询
5. get_all_daily_stats / get_stats_overview / get_calendar_data 委托方法
