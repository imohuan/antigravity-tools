# Antigravity Tools

多平台 IDE 工具管理器 — WorkBuddy / CodeBuddy 批量签到、API Key 代理、积分管理

## 功能

- **账号管理**：多平台账号统一管理（WorkBuddy / CodeBuddy 等）
- **批量签到**：每日自动签到 + 连续签到追踪
- **积分监控**：积分 / 配额实时查询，自动同步到代理池
- **API 代理服务**：本地代理转发请求到上游，支持多 Key 轮询 / 粘性会话 / 负载感知 / 故障转移
- **一键配置**：一键配置 WorkBuddy / CodeBuddy 客户端走本地代理
- **API 导入**：通过 API Key (ck_xxx) 快速导入账号
- **批量导入**：支持 JSON / 纯文本格式批量导入 API Key
- **设备指纹管理**：多设备指纹切换
- **多语言 / 主题切换**

## 下载安装

### Windows

1. 前往 [Releases](https://github.com/qinchangxv/antigravity-tools/releases) 下载 `Antigravity-Tools-Windows-x64.zip`
2. 解压后双击 `Antigravity Tools.exe` 运行

### macOS

1. 前往 [Releases](https://github.com/qinchangxv/antigravity-tools/releases) 下载对应芯片版本的 zip：
   - **Apple Silicon (M1/M2/M3/M4)**：`Antigravity-Tools-macOS-ARM.zip`
   - **Intel 芯片**：`Antigravity-Tools-macOS-Intel.zip`
2. 解压后将 `Antigravity Tools.app` 拖入「应用程序」文件夹
3. 首次打开如果提示"无法验证开发者"，参考下方 [常见问题排查](#常见问题排查-troubleshooting)

## 常见问题排查 (Troubleshooting)

### macOS 提示"应用已损坏，无法打开"？

由于 macOS 的安全机制，非 App Store 下载的应用可能会触发此提示。当前开源发布流程尚未接入 Apple Developer ID 签名和公证，因此部分系统版本会显示更严格的 Gatekeeper 提示。您可以按照以下步骤快速修复：

**命令行修复 (推荐):** 打开终端，执行以下命令：

```bash
sudo xattr -rd com.apple.quarantine "/Applications/Antigravity Tools.app"
```

> 注意: 如果您修改了应用名称或安装路径，请在命令中相应调整。

**或者:** 在「系统设置」→「隐私与安全性」中点击「仍要打开」

### 走代理后对话上下文越来越长 / 提示超限？

更新到 v1.5.6 及以上版本，已彻底修复此问题。如果仍遇到，请确认：

1. 软件版本 ≥ 1.5.6
2. 重新执行「一键配置 WorkBuddy」
3. 在 WorkBuddy 中**新建对话**（旧对话的上下文可能已经超限）

### 查分后代理池积分没更新？

更新到 v1.5.6 及以上版本，已修复积分同步问题。

## 开发

```bash
# 克隆仓库
git clone https://github.com/qinchangxv/antigravity-tools.git
cd antigravity-tools

# 创建虚拟环境
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

# 安装依赖
pip install -r requirements.txt

# 运行
python src/main.py
```

## 构建

```bash
# Windows
pyinstaller antigravity.spec

# macOS
pyinstaller antigravity-mac.spec
```

## 技术栈

- Python + PySide6 (Qt6)
- PyInstaller 打包
- GitHub Actions CI/CD

## License

MIT
