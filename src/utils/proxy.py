"""IP 代理工具模块 — 代理能力的唯一收口点

所有需要走代理的操作统一通过 get_proxy_from_settings() 获取代理 URL，
传入 ApiClient(proxy=...) 或 check_api_key_chat_status(proxy=...)。

两种代理模式：
1. API 提取模式（推荐）：填入代理 API 地址，应用自动调用 API 获取动态 IP:端口
2. 手动模式：直接填入 host:port

支持的协议：
- HTTP:    http://host:port
- HTTPS:   https://host:port
- SOCKS4:  socks4://host:port
- SOCKS5:  socks5h://host:port  (h = 远程 DNS，防止本地 DNS 泄露)

带认证格式：{scheme}://{username}:{password}@{host}:{port}
"""

import logging
import re
import time
from typing import Optional
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

# === 代理缓存（API 提取模式） ===
# 一号一IP：不缓存，每次调用都提取新 IP
_cached_proxy_url: str = ""
_cached_proxy_time: float = 0
_PROXY_CACHE_TTL: int = 0  # 缓存 0 秒 = 不缓存，每号一个新 IP


class ProxyConfigError(Exception):
    """代理配置异常（如 SOCKS 协议缺少 PySocks 依赖、API 提取失败等）"""


def build_proxy_url(
    protocol: str,
    host: str,
    port: str,
    username: str = "",
    password: str = "",
) -> str:
    """构建代理 URL

    Args:
        protocol: 协议类型 (http / https / socks4 / socks5)
        host: 代理服务器地址
        port: 代理服务器端口
        username: 用户名（可选）
        password: 密码（可选）

    Returns:
        代理 URL 字符串，如 socks5h://user:pass@127.0.0.1:1080
    """
    proto = protocol.lower().strip()

    # SOCKS5 使用 socks5h://（远程 DNS，防止本地 DNS 泄露）
    if proto == "socks5":
        scheme = "socks5h"
    elif proto == "socks4":
        scheme = "socks4"
    elif proto == "http":
        scheme = "http"
    elif proto == "https":
        scheme = "https"
    else:
        scheme = proto  # 透传未知协议

    if username and password:
        user_encoded = quote(username, safe="")
        pass_encoded = quote(password, safe="")
        return f"{scheme}://{user_encoded}:{pass_encoded}@{host}:{port}"
    elif username:
        user_encoded = quote(username, safe="")
        return f"{scheme}://{user_encoded}@{host}:{port}"
    else:
        return f"{scheme}://{host}:{port}"


def fetch_rolling_proxy(
    host: str,
    port: str,
    username: str,
    password: str,
    refresh_url_template: str,
    wait_seconds: float = 3.0,
    timeout: int = 15,
) -> dict:
    """滚动IP代理：固定地址+账号密码，通过刷新URL换IP。

    适用于 rola.vip 等提供"固定入口+刷新URL换IP"的代理服务商。
    协议固定走 SOCKS5h（远程DNS，兼容 Keycloak 风控检测）。

    Args:
        host: 代理服务器地址（如 gate.rola.vip）
        port: 代理端口
        username: 账号
        password: 密码
        refresh_url_template: 刷新URL模板，可用 {user} 占位符替换为 username
            例：https://refresh.rola.vip/refresh?user={user}&country=hk&state=&city=
        wait_seconds: 刷新后等待IP切换的秒数
        timeout: 请求超时秒数

    Returns:
        {
            "success": bool,
            "proxy_url": str,    # socks5h://user:pass@host:port
            "host": str,
            "port": str,
            "raw": str,          # 刷新响应内容
            "error": str,
        }
    """
    try:
        # 1. 调用刷新URL换IP（不通过代理，直接连接）
        url = refresh_url_template.format(user=username)
        session = requests.Session()
        session.trust_env = False
        session.verify = False
        session.proxies = {"http": None, "https": None}

        try:
            resp = session.get(url, timeout=timeout)
            refresh_text = resp.text.strip()[:200]
            logger.info(f"滚动IP: 刷新响应 {refresh_text}")
        except Exception as e:
            refresh_text = ""
            logger.warning(f"滚动IP: 刷新失败 {e}")

        # 2. 等待 IP 切换完成
        time.sleep(wait_seconds)

        # 3. 构建 SOCKS5h 代理 URL
        proto = "socks5h"
        if username and password:
            user_enc = quote(username, safe="")
            pass_enc = quote(password, safe="")
            proxy_url = f"{proto}://{user_enc}:{pass_enc}@{host}:{port}"
        else:
            proxy_url = f"{proto}://{host}:{port}"

        return {
            "success": True,
            "proxy_url": proxy_url,
            "host": host,
            "port": str(port),
            "raw": refresh_text,
            "error": "",
        }
    except Exception as e:
        return {
            "success": False,
            "proxy_url": "",
            "host": "",
            "port": "",
            "raw": "",
            "error": f"滚动IP刷新失败: {e}",
        }


def fetch_proxy_from_api(api_url: str, timeout: int = 10) -> dict:
    """调用代理 API 获取动态 IP:端口

    支持 txt 格式返回（如 "183.141.65.80:40036"），也支持多行返回（取第一行）。

    Args:
        api_url: 代理 API 地址
        timeout: 请求超时秒数

    Returns:
        {
            "success": bool,
            "host": str,     # IP 地址
            "port": str,     # 端口
            "raw": str,      # 原始响应
            "error": str,    # 失败时的错误信息
        }
    """
    try:
        session = requests.Session()
        session.trust_env = False
        session.proxies = {"http": None, "https": None}  # 获取代理本身不走代理

        resp = session.get(api_url, timeout=timeout)
        if resp.status_code != 200:
            return {
                "success": False,
                "host": "",
                "port": "",
                "raw": resp.text[:200],
                "error": f"API 返回 HTTP {resp.status_code}",
            }

        text = resp.text.strip()
        if not text:
            return {
                "success": False,
                "host": "",
                "port": "",
                "raw": "",
                "error": "API 返回空内容",
            }

        # 取第一行（API 可能返回多个 IP:port，每行一个）
        first_line = text.split("\n")[0].strip()

        # 匹配 ip:port 格式
        match = re.match(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d+)$', first_line)
        if match:
            host = match.group(1)
            port = match.group(2)
            logger.info(f"代理 API 提取成功: {host}:{port}")
            return {
                "success": True,
                "host": host,
                "port": port,
                "raw": first_line,
                "error": "",
            }

        # 也支持 domain:port 格式
        match = re.match(r'^([\w.-]+):(\d+)$', first_line)
        if match:
            host = match.group(1)
            port = match.group(2)
            logger.info(f"代理 API 提取成功: {host}:{port}")
            return {
                "success": True,
                "host": host,
                "port": port,
                "raw": first_line,
                "error": "",
            }

        # 无法解析
        return {
            "success": False,
            "host": "",
            "port": "",
            "raw": first_line[:200],
            "error": f"无法解析 API 返回内容: {first_line[:100]}",
        }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "host": "",
            "port": "",
            "raw": "",
            "error": "API 请求超时",
        }
    except Exception as e:
        return {
            "success": False,
            "host": "",
            "port": "",
            "raw": "",
            "error": f"API 请求失败: {e}",
        }


def get_proxy_from_settings() -> Optional[str]:
    """从设置中读取代理配置，返回代理 URL 或 None

    支持两种模式：
    - API 提取模式 (proxy_mode=api)：调用代理 API 获取动态 IP:端口，带缓存
    - 手动模式 (proxy_mode=static)：直接使用设置的 host:port

    Returns:
        代理 URL 字符串，或 None（未启用代理时）

    Raises:
        ProxyConfigError: SOCKS 协议但 PySocks 未安装，或 API 提取失败
    """
    global _cached_proxy_url, _cached_proxy_time

    from .store import load_setting

    enabled = load_setting("proxy_enabled", "false")
    if enabled != "true":
        return None

    protocol = load_setting("proxy_protocol", "http")
    mode = load_setting("proxy_mode", "api")  # 默认 API 模式
    username = load_setting("proxy_username", "").strip()
    password = load_setting("proxy_password", "")

    # SOCKS 协议需要 PySocks
    if protocol.lower() in ("socks4", "socks5"):
        try:
            import socks  # noqa: F401
        except ImportError:
            raise ProxyConfigError(
                "SOCKS 代理需要安装 PySocks 包：pip install PySocks"
            )

    if mode == "api":
        # === API 提取模式 ===
        api_url = load_setting("proxy_api_url", "").strip()
        if not api_url:
            logger.warning("代理 API 模式但未填 API 地址，跳过代理")
            return None

        # 检查缓存是否有效
        now = time.time()
        if _cached_proxy_url and (now - _cached_proxy_time) < _PROXY_CACHE_TTL:
            logger.debug(f"使用缓存的代理 URL: {_cached_proxy_url}")
            return _cached_proxy_url

        # 调用 API 获取动态 IP
        timeout = int(load_setting("proxy_timeout", "10"))
        result = fetch_proxy_from_api(api_url, timeout=timeout)
        if not result["success"]:
            raise ProxyConfigError(f"代理 API 提取失败: {result['error']}")

        proxy_url = build_proxy_url(
            protocol, result["host"], result["port"], username, password
        )

        # 更新缓存
        _cached_proxy_url = proxy_url
        _cached_proxy_time = now

        logger.info(f"✅ 获取代理成功 [API 模式] {protocol}://{result['host']}:{result['port']}")
        return proxy_url

    elif mode == "rolling":
        # === 滚动IP模式（rola.vip风格） ===
        # 固定地址+账号密码，调刷新URL换IP
        host = load_setting("proxy_host", "").strip()
        port = load_setting("proxy_port", "").strip()
        roll_user = load_setting("proxy_username", "").strip()
        roll_pass = load_setting("proxy_password", "")
        refresh_url = load_setting("proxy_refresh_url", "").strip()
        wait_seconds = float(load_setting("proxy_refresh_wait", "3"))

        if not host or not port:
            raise ProxyConfigError("滚动IP模式需填写代理地址和端口")
        if not refresh_url:
            raise ProxyConfigError("滚动IP模式需填写刷新URL")
        if not roll_user:
            raise ProxyConfigError("滚动IP模式需填写账号")

        # 检查 PySocks（SOCKS5h 必需）
        try:
            import socks  # noqa: F401
        except ImportError:
            raise ProxyConfigError("滚动IP模式使用 SOCKS5h 协议，需安装 PySocks：pip install PySocks")

        timeout = int(load_setting("proxy_timeout", "15"))
        result = fetch_rolling_proxy(
            host=host,
            port=port,
            username=roll_user,
            password=roll_pass,
            refresh_url_template=refresh_url,
            wait_seconds=wait_seconds,
            timeout=timeout,
        )
        if not result["success"]:
            raise ProxyConfigError(f"滚动IP刷新失败: {result['error']}")

        logger.info(f"✅ 获取代理成功 [滚动IP] socks5h://{host}:{port} (user={roll_user})")
        return result["proxy_url"]

    else:
        # === 手动模式 ===
        host = load_setting("proxy_host", "").strip()
        port = load_setting("proxy_port", "").strip()

        if not host or not port:
            logger.warning("代理已启用但地址/端口为空，跳过代理")
            return None

        url = build_proxy_url(protocol, host, port, username, password)
        logger.info(f"✅ 使用代理 [手动模式] {protocol}://{host}:{port}")
        return url


def invalidate_proxy_cache():
    """清除代理缓存（切换代理配置或手动刷新时调用）"""
    global _cached_proxy_url, _cached_proxy_time
    _cached_proxy_url = ""
    _cached_proxy_time = 0
    logger.info("代理缓存已清除")


def get_proxy_with_info() -> tuple:
    """获取代理 URL + 显示用 host:port

    每次调用都会从 API 提取新 IP（一号一IP）。

    Returns:
        (proxy_url, proxy_display):
        - proxy_url: 代理 URL 字符串，或 None（未启用代理）
        - proxy_display: 用于日志显示的 host:port，如 "116.26.37.101:40031"
          未启用代理时返回空字符串
    """
    try:
        proxy_url = get_proxy_from_settings()
    except ProxyConfigError as e:
        logger.warning(f"代理获取失败: {e}")
        return None, ""
    if not proxy_url:
        return None, ""

    # 从 URL 提取 host:port
    url = proxy_url
    for prefix in ("http://", "https://", "socks4://", "socks5h://", "socks5://"):
        if url.startswith(prefix):
            url = url[len(prefix):]
            break
    if "@" in url:
        url = url.split("@", 1)[1]
    return proxy_url, url


def describe_proxy_status() -> str:
    """返回当前代理状态的人类可读描述（用于 UI 日志显示）

    Returns:
        状态描述字符串，例如：
        - "未启用代理"
        - "✅ 已启用代理 (API 模式): HTTP://117.86.31.236:40005"
        - "⚠️ 代理已启用但配置不完整"
    """
    from .store import load_setting

    enabled = load_setting("proxy_enabled", "false")
    if enabled != "true":
        return "未启用代理"

    protocol = load_setting("proxy_protocol", "HTTP")
    mode = load_setting("proxy_mode", "api")
    api_url = load_setting("proxy_api_url", "").strip()
    host = load_setting("proxy_host", "").strip()
    port = load_setting("proxy_port", "").strip()

    if mode == "api":
        if api_url:
            return f"✅ 已启用代理 (API 模式): {protocol} — 每号一IP"
        return "⚠️ 代理已启用但未填 API 地址"
    elif mode == "rolling":
        refresh_url = load_setting("proxy_refresh_url", "").strip()
        if host and port and refresh_url:
            return f"✅ 已启用代理 (滚动IP): socks5h://{host}:{port} — 每号一IP"
        return "⚠️ 代理已启用但滚动IP配置不完整（需地址/端口/刷新URL）"
    else:
        if host and port:
            return f"✅ 已启用代理 (手动模式): {protocol}://{host}:{port}"
        return "⚠️ 代理已启用但未填地址/端口"


def test_proxy_connection(proxy_url: str, timeout: int = 10) -> dict:
    """测试代理连通性

    照搬 codebuddy_ui.py _verify_proxy 的两步验证逻辑：

    第1步：HTTPS 隧道验证 — 请求 https://myip.ipip.net
           - 407 → 代理需要认证，直接判失败
           - 200 → HTTPS 隧道通过
           - 其他异常 → 记录错误，继续第2步（不直接判死）

    第2步：获取出口 IP + 国家信息
           - http://ip-api.com/json（主，返回 query/country/countryCode）
           - https://ipinfo.io/json（备，返回 ip/country）
           - 407 → 代理需要认证，直接判失败
           - JSON 解析失败 → 正则抠 IP
           - 拿到 IP 即成功

    Args:
        proxy_url: 代理 URL（由 build_proxy_url 构建）
        timeout: 超时秒数

    Returns:
        {
            "success": bool,
            "latency_ms": int,       # 第2步 HTTP 请求的延迟
            "ip": str,               # 代理出口 IP
            "country": str,          # 国家名（如 "Hong Kong"）
            "country_code": str,     # 国家代码（如 "HK"）
            "error": str,            # 失败时的错误信息
        }
    """
    session = requests.Session()
    session.trust_env = False
    session.proxies = {"http": proxy_url, "https": proxy_url}
    # HTTPS 代理的 TLS 证书通常是自签名/IP 证书，不验证
    session.verify = False

    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    last_error = ""
    got_ip = ""
    got_country = ""
    got_country_code = ""

    # ---- 第1步：HTTPS 隧道验证 ----
    try:
        resp = session.get("https://myip.ipip.net", timeout=timeout)
        if resp.status_code == 407:
            return {
                "success": False, "latency_ms": 0, "ip": "",
                "country": "", "country_code": "",
                "error": "代理需要认证，但未提供有效的账号密码 (HTTP 407)",
            }
        if resp.status_code == 200:
            logger.info("代理 HTTPS 隧道验证通过")
    except Exception as e:
        last_error = str(e)
        if "407" in last_error or "Proxy Authentication Required" in last_error:
            return {
                "success": False, "latency_ms": 0, "ip": "",
                "country": "", "country_code": "",
                "error": "代理需要认证，但未提供有效的账号密码 (HTTP 407)",
            }
        # 其他异常不直接判死，继续第2步

    # ---- 第2步：获取出口 IP + 国家信息 ----
    for url in ["http://ip-api.com/json", "http://ipv4.icanhazip.com"]:
        try:
            start = time.time()
            resp = session.get(url, timeout=timeout)
            latency = int((time.time() - start) * 1000)

            if resp.status_code == 407:
                return {
                    "success": False, "latency_ms": 0, "ip": "",
                    "country": "", "country_code": "",
                    "error": "代理需要认证，但未提供有效的账号密码 (HTTP 407)",
                }

            try:
                data = resp.json()
                # ip-api.com 格式: {query: "IP", country: "Hong Kong", countryCode: "HK"}
                # icanhazip 格式: {"ip": "IP"}（只返回 IP，没有国家）
                ip = data.get("ip") or data.get("origin") or data.get("query") or ""
                if not got_country:
                    got_country = data.get("country", "")
                if not got_country_code:
                    got_country_code = data.get("countryCode", "")
                # ipinfo.io 的 country 字段是国家代码（如 "HK"），不是国家名
                if not got_country_code and got_country and len(got_country) == 2:
                    got_country_code = got_country
            except (ValueError, Exception):
                # icanhazip 直接返回纯文本 IP
                text = resp.text.strip()
                m = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', text)
                ip = m.group(1) if m else ""

            if ip:
                got_ip = ip

            # 如果已经有 IP + 国家信息，不需要再试备用 API
            if got_ip and got_country_code:
                break
        except Exception as e:
            last_error = str(e)
            if "407" in last_error or "Proxy Authentication Required" in last_error:
                return {
                    "success": False, "latency_ms": 0, "ip": "",
                    "country": "", "country_code": "",
                    "error": "代理需要认证，但未提供有效的账号密码 (HTTP 407)",
                }
            continue

    # ---- 结果判断 ----
    if got_ip:
        country_info = f" ({got_country}/{got_country_code})" if got_country else ""
        logger.info(f"代理出口IP验证: {got_ip}{country_info}")
        return {
            "success": True,
            "latency_ms": latency,
            "ip": got_ip,
            "country": got_country,
            "country_code": got_country_code,
            "error": "",
        }

    # 没有获取到 IP
    logger.warning("代理出口IP验证失败（或代理不支持HTTPS隧道）")
    return {
        "success": False,
        "latency_ms": 0,
        "ip": "",
        "country": "",
        "country_code": "",
        "error": last_error[:120] if last_error else "代理连接失败：无法获取出口IP",
    }
