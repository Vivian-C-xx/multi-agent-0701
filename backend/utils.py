import html
import os
from pathlib import Path
from uuid import uuid4

from backend.config import ALLOWED_EXTENSIONS, BASE_DIR, TEMPLATE_DIR

def load_env_file():
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

def ensure_deepseek_api_key():
    if os.getenv("DEEPSEEK_API_KEY"):
        return
    try:
        api_key = input("请输入 DeepSeek API Key: ").strip()
    except EOFError:
        api_key = ""
    if api_key:
        os.environ["DEEPSEEK_API_KEY"] = api_key
        print("DeepSeek API Key 已加载，本次运行可直接调用模型。")
    else:
        print("未输入 DeepSeek API Key。启动后聊天接口会提示需要配置密钥。")

def esc(value):
    return html.escape(str(value or ""), quote=True)

def read_template(name):
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def secure_name(filename):
    cleaned = Path(filename).name.replace("\\", "_").replace("/", "_")
    return "".join(ch for ch in cleaned if ch.isalnum() or ch in "._-()[]") or "upload.bin"

def ensure_student_state(state):
    state.setdefault("student_session_id", str(uuid4()))
    state.setdefault("conversation", [])
    state.setdefault("debug_count", 0)
    state.setdefault("learning_phase", "主题作品体验")
    state.setdefault("learning_step", "topic_intro")
    state.setdefault("current_topic", "")
    state.setdefault("exercise_prompt", "")
    state.setdefault("plan_synced", False)
    state.setdefault("time_plan", [])

def contains_any(message, words):
    return any(word in message for word in words)
