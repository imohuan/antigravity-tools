"""设置页面"""

import os
import sys

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QComboBox, QSpinBox, QLineEdit, QCheckBox, QGroupBox, QFormLayout
)
from PySide6.QtCore import Qt

from ...i18n import t, set_language, get_language
from ...utils.store import save_setting, load_setting
from ..styles import get_stylesheet


class SettingsPage(QWidget):
    """设置页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("content_area")
        self._main_window = None
        self._setup_ui()

    def set_main_window(self, window):
        self._main_window = window

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel(t("settings.title"))
        title.setObjectName("page_title")
        layout.addWidget(title)

        subtitle = QLabel("配置应用行为和外观")
        subtitle.setObjectName("page_subtitle")
        layout.addWidget(subtitle)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 0, 32, 32)
        content_layout.setSpacing(20)

        # === 通用设置 ===
        general_group = QGroupBox("🎨 " + t("settings.general"))
        general_form = QFormLayout(general_group)
        general_form.setSpacing(12)
        general_form.setContentsMargins(20, 24, 20, 20)

        # 主题
        self._theme_combo = QComboBox()
        self._theme_combo.addItems([t("settings.theme_light"), t("settings.theme_dark"), t("settings.theme_system")])
        self._theme_combo.setCurrentIndex(2)  # 默认跟随系统
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        general_form.addRow(t("settings.theme") + ":", self._theme_combo)

        # 语言
        self._lang_combo = QComboBox()
        self._lang_combo.addItems(["简体中文", "English"])
        self._lang_combo.setCurrentIndex(0)
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        general_form.addRow(t("settings.language") + ":", self._lang_combo)

        # UI 缩放
        self._scale_spin = QSpinBox()
        self._scale_spin.setRange(80, 200)
        self._scale_spin.setValue(100)
        self._scale_spin.setSuffix("%")
        general_form.addRow(t("settings.ui_scale") + ":", self._scale_spin)

        # 关闭行为
        self._close_combo = QComboBox()
        self._close_combo.addItems([t("settings.close_minimize"), t("settings.close_exit")])
        general_form.addRow(t("settings.close_behavior") + ":", self._close_combo)

        # 开机自启
        self._startup_check = QCheckBox(t("settings.show_on_startup"))
        general_form.addRow("", self._startup_check)

        content_layout.addWidget(general_group)

        # === 刷新设置 ===
        refresh_group = QGroupBox("🔄 配额刷新")
        refresh_form = QFormLayout(refresh_group)
        refresh_form.setSpacing(12)
        refresh_form.setContentsMargins(20, 24, 20, 20)

        self._refresh_spin = QSpinBox()
        self._refresh_spin.setRange(5, 120)
        self._refresh_spin.setValue(30)
        self._refresh_spin.setSuffix(" 分钟")
        refresh_form.addRow(t("settings.auto_refresh") + ":", self._refresh_spin)

        content_layout.addWidget(refresh_group)

        # 保存按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_save = QPushButton("💾 保存设置")
        btn_save.setObjectName("primary_btn")
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.clicked.connect(self._save_settings)
        btn_row.addWidget(btn_save)

        content_layout.addLayout(btn_row)
        content_layout.addStretch()
        layout.addWidget(content)

    def _on_theme_changed(self, index: int):
        """主题切换"""
        themes = ["light", "dark", "system"]
        theme = themes[index]
        save_setting("theme", theme)
        if self._main_window:
            self._main_window.apply_theme(theme)

    def _on_language_changed(self, index: int):
        """语言切换"""
        langs = ["zh-CN", "en"]
        lang = langs[index]
        set_language(lang)
        save_setting("language", lang)

    def _save_settings(self):
        """保存所有设置"""
        save_setting("ui_scale", str(self._scale_spin.value()))
        save_setting("close_behavior", "minimize" if self._close_combo.currentIndex() == 0 else "exit")
        save_setting("startup", str(self._startup_check.isChecked()))
        save_setting("refresh_interval", str(self._refresh_spin.value()))

        # 开机自启动
        startup_enabled = self._startup_check.isChecked()
        self._set_auto_startup(startup_enabled)

        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, t("common.success"), "设置已保存")

    @staticmethod
    def _set_auto_startup(enable: bool):
        """设置开机自启动（Windows: 注册表 / macOS: LaunchAgent）"""
        try:
            if sys.platform == "win32":
                import winreg
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                app_name = "AntigravityTools"
                if enable:
                    if getattr(sys, 'frozen', False):
                        exe_path = f'"{sys.executable}"'
                    else:
                        exe_path = f'"{sys.executable}" "{os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "main.py"))}"'
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                        winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
                else:
                    try:
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                            winreg.DeleteValue(key, app_name)
                    except FileNotFoundError:
                        pass
            elif sys.platform == "darwin":
                # macOS: 使用 LaunchAgent plist
                plist_dir = os.path.expanduser("~/Library/LaunchAgents")
                os.makedirs(plist_dir, exist_ok=True)
                plist_path = os.path.join(plist_dir, "com.antigravity.tools.plist")
                if enable:
                    if getattr(sys, 'frozen', False):
                        exe_path = sys.executable
                    else:
                        exe_path = f'{sys.executable} {os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "main.py"))}'
                    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.antigravity.tools</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>"""
                    with open(plist_path, "w", encoding="utf-8") as f:
                        f.write(plist_content)
                else:
                    if os.path.exists(plist_path):
                        os.remove(plist_path)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"设置开机自启动失败: {e}")

    def showEvent(self, event):
        """加载已保存的设置"""
        super().showEvent(event)
        # 防止重复加载导致信号触发
        self._theme_combo.blockSignals(True)
        self._lang_combo.blockSignals(True)
        self._close_combo.blockSignals(True)

        try:
            # 主题
            theme = load_setting("theme", "system")
            themes = ["light", "dark", "system"]
            if theme in themes:
                self._theme_combo.setCurrentIndex(themes.index(theme))

            # 语言
            lang = load_setting("language", "zh-CN")
            self._lang_combo.setCurrentIndex(0 if lang == "zh-CN" else 1)

            # 缩放
            scale = int(load_setting("ui_scale", "100"))
            self._scale_spin.setValue(scale)

            # 关闭行为
            close_behavior = load_setting("close_behavior", "minimize")
            self._close_combo.setCurrentIndex(0 if close_behavior == "minimize" else 1)

            # 开机自启
            self._startup_check.setChecked(load_setting("startup", "False") == "True")

            # 刷新间隔
            refresh = int(load_setting("refresh_interval", "30"))
            self._refresh_spin.setValue(refresh)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"加载设置失败: {e}")
        finally:
            self._theme_combo.blockSignals(False)
            self._lang_combo.blockSignals(False)
            self._close_combo.blockSignals(False)
