"""Antigravity Tools - PyInstaller 入口文件

此文件是打包的入口点，将 src 包路径添加到 sys.path 后启动应用。
直接运行此文件等同于 python -m src.main

[v1.6.3-fix] 使用 exec 动态加载 src/main.py，避免 PyInstaller 将 src/ 编译进 PYZ。
这样增量更新替换 src/ 目录的 .py 文件才能生效。
"""

import sys
import os
import importlib

# 将项目根目录加入 sys.path，使 `from src.xxx` 正常工作
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# PyInstaller 打包后，_MEIPASS 指向 _internal/ 目录
# src/ 作为 datas 打包在 _internal/src/，需要把 _MEIPASS 加入 sys.path
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
    if base_path not in sys.path:
        sys.path.insert(0, base_path)

# 动态加载 src.main 模块并执行 main()
# 不用 `from src.main import main` 是因为 PyInstaller 静态分析会跟踪 import 链
# 把 src/ 编译进 PYZ，导致运行时不读 .py 文件，增量更新失效
_mod = importlib.import_module('src.main')
_mod.main()
