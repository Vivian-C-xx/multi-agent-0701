import json
import os
import socket
import ssl
import urllib.error
import urllib.request

from backend.agents.prompt_builder import build_system_prompt
from backend.config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL


API_PATH = "/chat/completions"


def _normalize_base_url(value):
    base_url = (value or DEEPSEEK_BASE_URL).strip().rstrip("/")
    if not base_url:
        base_url = DEEPSEEK_BASE_URL
    if not base_url.startswith(("http://", "https://")):
        base_url = f"https://{base_url}"
    if base_url.endswith(API_PATH):
        base_url = base_url[: -len(API_PATH)].rstrip("/")
    return base_url


def _api_url():
    return f"{_normalize_base_url(os.getenv('DEEPSEEK_BASE_URL'))}{API_PATH}"


def _timeout_seconds():
    try:
        return max(1.0, float(os.getenv("DEEPSEEK_TIMEOUT", "45")))
    except ValueError:
        return 45.0


def _proxy_env_summary():
    proxy_keys = ["HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"]
    proxies = [key for key in proxy_keys if os.getenv(key)]
    return "、".join(proxies)


def _is_connection_refused(exc):
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ConnectionRefusedError):
        return True
    if getattr(reason, "winerror", None) == 10061:
        return True
    return "10061" in str(exc) or "Connection refused" in str(exc)


def _network_error_message(exc, retried_without_proxy=False):
    base_url = _normalize_base_url(os.getenv("DEEPSEEK_BASE_URL"))
    proxy_keys = _proxy_env_summary()
    tips = [
        f"当前接口地址：{base_url}",
        "请确认本机能访问 DeepSeek API，并检查 DEEPSEEK_BASE_URL 是否填写正确。",
    ]
    if proxy_keys:
        tips.append(f"检测到代理环境变量：{proxy_keys}。如果代理软件未启动，请启动代理或清空这些代理配置。")
    if retried_without_proxy:
        tips.append("系统已自动尝试绕过代理直连一次，但仍未连接成功。")
    if _is_connection_refused(exc):
        return "大模型 API 连接被拒绝，暂时无法获得回答。\n" + "\n".join(tips)
    if isinstance(getattr(exc, "reason", exc), socket.timeout):
        return "连接大模型 API 超时，请稍后重试或检查网络状态。\n" + "\n".join(tips)
    if isinstance(getattr(exc, "reason", exc), ssl.SSLError):
        return "连接大模型 API 时 SSL 校验失败，请检查系统时间、证书或代理配置。\n" + "\n".join(tips)
    return "暂时无法连接大模型 API，请稍后重试。\n" + "\n".join(tips)


def _parse_error_detail(exc):
    detail = exc.read().decode("utf-8", errors="ignore")
    try:
        data = json.loads(detail)
        message = data.get("error", {}).get("message") or data.get("message")
        if message:
            return message[:500]
    except json.JSONDecodeError:
        pass
    return detail[:500]


def _http_error_message(exc):
    detail = _parse_error_detail(exc)
    if exc.code in {401, 403}:
        return f"大模型 API 鉴权失败（HTTP {exc.code}）。请检查 DEEPSEEK_API_KEY 是否正确或是否有可用额度。"
    if exc.code == 404:
        return f"大模型 API 地址不存在（HTTP 404）。请检查 DEEPSEEK_BASE_URL 和 DEEPSEEK_MODEL 配置。"
    if exc.code == 429:
        return "大模型 API 请求过于频繁或额度不足（HTTP 429）。请稍后重试。"
    if 500 <= exc.code < 600:
        return f"大模型 API 服务暂时异常（HTTP {exc.code}），请稍后重试。"
    return f"大模型 API 返回错误（HTTP {exc.code}）。请检查模型、密钥或接口地址。\n{detail}"


def _open_request(req, timeout, use_proxy=True):
    if use_proxy:
        return urllib.request.urlopen(req, timeout=timeout)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=timeout)


def _read_content(resp):
    data = json.loads(resp.read().decode("utf-8"))
    content = data["choices"][0]["message"].get("content", "").strip()
    return content or "大模型返回了空内容，请稍后重试或检查模型配置。"


def call_llm(state, agent, message):
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return "还没有配置 DeepSeek API 密钥。请在启动程序时输入密钥，或在 .env 中设置 DEEPSEEK_API_KEY 后重新启动。"

    model = os.getenv("DEEPSEEK_MODEL", DEEPSEEK_MODEL).strip() or DEEPSEEK_MODEL
    messages = [{"role": "system", "content": build_system_prompt(agent, state)}]
    messages.extend(state.get("conversation", [])[-12:])
    messages.append({"role": "user", "content": message})
    payload_data = {"model": model, "messages": messages, "temperature": 0.7, "max_tokens": 900}
    payload = json.dumps(payload_data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        _api_url(),
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    timeout = _timeout_seconds()

    try:
        with _open_request(req, timeout) as resp:
            return _read_content(resp)
    except urllib.error.HTTPError as exc:
        return _http_error_message(exc)
    except urllib.error.URLError as exc:
        if _is_connection_refused(exc) and _proxy_env_summary():
            try:
                with _open_request(req, timeout, use_proxy=False) as resp:
                    return _read_content(resp)
            except urllib.error.HTTPError as retry_exc:
                return _http_error_message(retry_exc)
            except urllib.error.URLError as retry_exc:
                return _network_error_message(retry_exc, retried_without_proxy=True)
            except Exception as retry_exc:
                return f"大模型 API 返回内容解析失败：{retry_exc}"
        return _network_error_message(exc)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        return f"大模型 API 返回内容格式异常：{exc}"
    except Exception as exc:
        return f"调用大模型 API 时遇到未知问题：{exc}"
