import csv
import json
import os
import re
import time
from datetime import datetime
from io import StringIO
from pathlib import Path
from uuid import uuid4

import streamlit as st

from backend.agents.router_agent import AGENT_NAMES, agent_notice, manager_refusal, route_agent
from backend.services.knowledge_base import build_knowledge_summary, existing_upload_rows, extract_text
from backend.services.learning_flow import clean_reply, decorate_message, maybe_append_auto_followup, prepare_step_for_prompt
from backend.services.llm_client import call_llm
from backend.storage import db_rows, execute, init_storage, save_interaction
from backend.upload_store import choose_upload_dir, find_upload_file, iter_upload_files
from backend.utils import allowed_file, ensure_student_state, load_env_file, secure_name


st.set_page_config(
    page_title="编程自主学习伙伴",
    page_icon=":material/school:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def load_runtime_config():
    load_env_file()
    for key in [
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_TIMEOUT",
        "TEACHER_USERNAME",
        "TEACHER_PASSWORD",
        "APP_DB_PATH",
        "APP_UPLOAD_DIR",
    ]:
        try:
            value = st.secrets.get(key)
        except Exception:
            value = None
        if value and key not in os.environ:
            os.environ[key] = str(value)


@st.cache_resource
def initialize_app():
    load_runtime_config()
    init_storage()
    return True


def student_state():
    state = st.session_state.setdefault("student_state", {})
    ensure_student_state(state)
    return state


def agent_options():
    return {
        "编程自主学习管家": "auto",
        "助教智能体": "assistant",
        "导师智能体": "mentor",
        "同伴智能体": "peer",
    }


TASK_LABELS = {
    "分析问题": "分析",
    "设计算法": "算法",
    "编写程序": "编程",
    "代码优化": "优化",
}

DEFAULT_TIME_PLAN = [
    {"name": "分析问题", "label": "分析", "minutes": 5},
    {"name": "设计算法", "label": "算法", "minutes": 5},
    {"name": "编写程序", "label": "编程", "minutes": 7},
    {"name": "代码优化", "label": "优化", "minutes": 3},
]

TIME_PLAN_WIDGET_PREFIX = "time_plan_input"
PEER_MONITOR_TITLE = "同伴智能体监督区"
CHAT_AVATARS = {
    "user": "static/agent_avatars/user.svg",
    "manager": "static/agent_avatars/manager.svg",
    "assistant": "static/agent_avatars/assistant.svg",
    "mentor": "static/agent_avatars/mentor.svg",
    "peer": "static/agent_avatars/peer.svg",
}
COMPLETION_WORDS = [
    "已完成",
    "完成了",
    "做完了",
    "完成任务",
    "任务完成",
    "分析完成",
    "算法完成",
    "编写完成",
    "优化完成",
    "流程图完成",
    "流程图正确",
    "代码写完",
    "编写完代码",
    "IPO正确",
    "分析正确",
    "结束问题分析",
    "完全正确",
    "调试成功",
    "运行成功",
    "问题解决",
    "进入下一任务",
]
LEARNING_STEP_TASK_INDEX = {
    "ipo_analysis": 0,
    "flowchart": 1,
    "debugging": 2,
    "self_evaluation": 3,
}


def inject_student_page_styles():
    st.markdown(
        """
        <style>
        .peer-monitor-title {
            margin: 0 0 10px 0;
            color: #2f3340;
            font-size: 18px;
            font-weight: 800;
            line-height: 1.2;
            letter-spacing: 0;
            white-space: normal;
        }
        .peer-current-task {
            margin-top: 6px;
            color: #2f3340;
            font-size: 19px;
            font-weight: 800;
            line-height: 1.15;
            letter-spacing: 0;
        }
        .peer-timer-text {
            font-size: 36px;
            font-weight: 800;
            color: #f45f5f;
            line-height: 1;
            letter-spacing: 0;
        }
        .st-key-peer_monitor_fixed,
        .st-key-peer-monitor-fixed {
            position: fixed;
            top: 28px;
            right: 24px;
            width: clamp(360px, 27vw, 430px);
            max-height: calc(100vh - 36px);
            overflow-y: auto;
            padding-bottom: 4px;
            z-index: 20;
            background: #ffffff;
        }
        .st-key-peer_monitor_fixed [data-testid="stVerticalBlock"] {
            gap: 0.34rem;
        }
        .st-key-peer_monitor_fixed [data-testid="stVerticalBlockBorderWrapper"] {
            padding: 0.58rem 0.72rem;
        }
        .st-key-peer_monitor_fixed [data-testid="stVerticalBlockBorderWrapper"]:has(.peer-current-task) {
            min-height: 74px;
        }
        .st-key-peer_monitor_fixed [data-testid="stVerticalBlockBorderWrapper"]:has(.peer-timer-text) {
            min-height: 78px;
        }
        .st-key-peer_monitor_fixed [data-testid="stCaptionContainer"] {
            font-size: 0.75rem;
        }
        .st-key-peer_monitor_fixed [data-testid="stNumberInput"] label {
            font-size: 0.82rem;
            margin-bottom: 0.15rem;
        }
        .st-key-peer_monitor_fixed [data-testid="stNumberInput"] input {
            min-height: 32px;
            padding-top: 0.2rem;
            padding-bottom: 0.2rem;
            font-size: 0.85rem;
        }
        .st-key-peer_monitor_fixed button {
            min-height: 32px;
            padding-top: 0.25rem;
            padding-bottom: 0.25rem;
        }
        .peer-debug-row {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 12px;
            padding: 0;
        }
        .peer-debug-label {
            color: #8b909b;
            font-size: 0.78rem;
        }
        .peer-debug-value {
            color: #2f3340;
            font-size: 22px;
            font-weight: 800;
            line-height: 1;
        }
        .st-key-chat_scroll_area,
        .st-key-chat-scroll-area {
            height: calc(100vh - 220px);
            overflow-y: auto;
            padding-right: 0.65rem;
        }
        .st-key-chat_scroll_area [data-testid="stVerticalBlock"],
        .st-key-chat-scroll-area [data-testid="stVerticalBlock"] {
            gap: 0.85rem;
        }
        div[data-testid="column"]:has(.st-key-peer_monitor_fixed),
        div[data-testid="column"]:has(.st-key-peer-monitor-fixed) {
            min-height: calc(100vh - 120px);
        }
        @media (max-width: 1100px) {
            .peer-monitor-title {
                font-size: 17px;
            }
            .peer-current-task {
                font-size: 19px;
            }
            .peer-timer-text {
                font-size: 34px;
            }
        }
        @media (max-width: 900px) {
            .st-key-chat_scroll_area,
            .st-key-chat-scroll-area {
                height: auto;
                overflow-y: visible;
                padding-right: 0;
            }
            .st-key-peer_monitor_fixed,
            .st-key-peer-monitor-fixed {
                position: static;
                width: auto;
                max-height: none;
                overflow-y: visible;
                background: transparent;
            }
            div[data-testid="column"]:has(.st-key-peer_monitor_fixed),
            div[data-testid="column"]:has(.st-key-peer-monitor-fixed) {
                min-height: auto;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def timer_state():
    return st.session_state.setdefault(
        "timer_state",
        {
            "running": False,
            "started_at": None,
            "elapsed_before_pause": 0.0,
            "current_task_index": 0,
            "completed_tasks": 0,
        },
    )


def normalize_time_plan(source_plan):
    plan = []
    for idx, task in enumerate((source_plan or DEFAULT_TIME_PLAN)[:4]):
        default = DEFAULT_TIME_PLAN[min(idx, len(DEFAULT_TIME_PLAN) - 1)]
        name = task.get("name") or default["name"]
        plan.append(
            {
                "name": name,
                "label": TASK_LABELS.get(name, task.get("label") or default["label"]),
                "minutes": int(task.get("minutes", default["minutes"])),
            }
        )
    return plan[:4]


def active_time_plan(state):
    source_plan = st.session_state.get("manual_time_plan") or state.get("time_plan") or DEFAULT_TIME_PLAN
    return normalize_time_plan(source_plan)


def has_estimated_time_plan(state):
    return bool(state.get("plan_synced") or st.session_state.get("time_plan_estimated"))


def same_minutes(left_plan, right_plan):
    left = normalize_time_plan(left_plan)
    right = normalize_time_plan(right_plan)
    return [task["minutes"] for task in left] == [task["minutes"] for task in right]


def set_active_time_plan(state, plan):
    normalized = normalize_time_plan(plan)
    state["time_plan"] = normalized
    st.session_state["manual_time_plan"] = normalized
    st.session_state["time_plan_estimated"] = True
    st.session_state["time_plan_version"] = int(st.session_state.get("time_plan_version", 0)) + 1
    return normalized


def total_plan_seconds(plan):
    return max(0, sum(task["minutes"] for task in plan) * 60)


def cumulative_task_seconds(plan, task_index):
    if not plan:
        return 0
    end_index = min(max(task_index, 0), len(plan) - 1) + 1
    return max(0, sum(task["minutes"] for task in plan[:end_index]) * 60)


def elapsed_timer_seconds(timer):
    elapsed = float(timer.get("elapsed_before_pause", 0.0))
    if timer.get("running") and timer.get("started_at"):
        elapsed += time.time() - float(timer["started_at"])
    return max(0, elapsed)


def remaining_timer_seconds(plan, timer):
    return max(0, int(total_plan_seconds(plan) - elapsed_timer_seconds(timer)))


def current_task_remaining_seconds(plan, timer):
    current_index = min(int(timer.get("current_task_index", 0)), max(len(plan) - 1, 0))
    return max(0, int(cumulative_task_seconds(plan, current_index) - elapsed_timer_seconds(timer)))


def format_seconds(seconds):
    minutes, secs = divmod(max(0, int(seconds)), 60)
    return f"{minutes:02d}:{secs:02d}"


def start_timer():
    timer = timer_state()
    if not timer.get("running"):
        timer["running"] = True
        timer["started_at"] = time.time()


def pause_timer():
    timer = timer_state()
    if timer.get("running") and timer.get("started_at"):
        timer["elapsed_before_pause"] = elapsed_timer_seconds(timer)
    timer["running"] = False
    timer["started_at"] = None


def current_timer_task(plan, timer):
    if not plan:
        return 0, {"name": "分析问题", "label": "分析", "minutes": 0}
    current_index = min(int(timer.get("current_task_index", 0)), len(plan) - 1)
    return current_index, plan[current_index]


def advance_timer_task(state, reason="auto"):
    plan = active_time_plan(state)
    timer = timer_state()
    current_index, current_task = current_timer_task(plan, timer)
    if not plan:
        return None
    next_index = min(current_index + 1, len(plan) - 1)
    timer["completed_tasks"] = min(max(int(timer.get("completed_tasks", 0)), current_index + 1), len(plan))
    timer["current_task_index"] = next_index
    timer.pop("overtime_notice_key", None)
    if timer["completed_tasks"] >= len(plan):
        pause_timer()
    elif not timer.get("running"):
        start_timer()
    return {
        "completed_task": current_task["name"],
        "next_task": plan[next_index]["name"],
        "reason": reason,
        "all_done": timer["completed_tasks"] >= len(plan),
    }


def sync_timer_task_from_learning_step(state, metadata=None):
    if not has_estimated_time_plan(state):
        return None
    plan = active_time_plan(state)
    if not plan:
        return None
    step = state.get("learning_step")
    target_index = LEARNING_STEP_TASK_INDEX.get(step)
    if target_index is None:
        return None

    timer = timer_state()
    current_index = min(int(timer.get("current_task_index", 0)), len(plan) - 1)
    target_index = min(target_index, len(plan) - 1)
    if target_index <= current_index:
        return None

    timer["completed_tasks"] = max(int(timer.get("completed_tasks", 0)), target_index)
    timer["current_task_index"] = target_index
    timer.pop("overtime_notice_key", None)
    if metadata is not None:
        metadata["timer_synced_to_learning_step"] = step
        metadata["rerun_after_timer_update"] = True
    return {"from": current_index, "to": target_index, "step": step}


def reset_timer():
    st.session_state["timer_state"] = {
        "running": False,
        "started_at": None,
        "elapsed_before_pause": 0.0,
        "current_task_index": 0,
        "completed_tasks": 0,
    }


def reset_time_plan_session():
    st.session_state.pop("manual_time_plan", None)
    st.session_state.pop("time_plan_estimated", None)
    st.session_state["time_plan_version"] = int(st.session_state.get("time_plan_version", 0)) + 1
    for key in list(st.session_state.keys()):
        if str(key).startswith(f"{TIME_PLAN_WIDGET_PREFIX}_"):
            st.session_state.pop(key, None)


def sync_timer_from_metadata(metadata):
    if metadata.get("time_plan"):
        state = student_state()
        set_active_time_plan(state, metadata["time_plan"])
        reset_timer()
    if metadata.get("reset_timer"):
        reset_timer()
    if metadata.get("start_timer") and not metadata.get("delay_timer_start"):
        start_timer()
    if metadata.get("pause_timer") or metadata.get("complete_timer"):
        pause_timer()
    if metadata.get("complete_timer"):
        timer = timer_state()
        timer["completed_tasks"] = len(DEFAULT_TIME_PLAN)


def update_manual_plan(state, plan):
    edited_plan = []
    cols = st.columns(2, gap="small")
    version = int(st.session_state.get("time_plan_version", 0))
    for idx, task in enumerate(plan):
        with cols[idx % 2]:
            minutes = st.number_input(
                task["label"],
                min_value=0,
                max_value=60,
                value=int(task["minutes"]),
                step=1,
                key=f"{TIME_PLAN_WIDGET_PREFIX}_{version}_{idx}_{task['label']}",
            )
        edited_plan.append({**task, "minutes": int(minutes)})
    st.session_state["manual_time_plan"] = edited_plan
    if not same_minutes(edited_plan, DEFAULT_TIME_PLAN):
        st.session_state["time_plan_estimated"] = True
        state["time_plan"] = edited_plan
    return edited_plan


def render_timer_panel(state):
    plan = active_time_plan(state)
    timer = timer_state()
    estimated_plan = has_estimated_time_plan(state)
    current_index = min(int(timer.get("current_task_index", 0)), len(plan) - 1)
    current_task = plan[current_index]["name"] if plan else "分析问题"
    remaining = current_task_remaining_seconds(plan, timer) if estimated_plan else remaining_timer_seconds(plan, timer)
    total_minutes = sum(task["minutes"] for task in plan)
    completed = min(int(timer.get("completed_tasks", 0)), len(plan))
    progress = completed / len(plan) if plan else 0

    with st.container(border=True):
        st.caption("当前任务")
        st.markdown(f"<div class='peer-current-task'>当前任务：{current_task}</div>", unsafe_allow_html=True)

    with st.container(border=True):
        st.caption("当前任务剩余时间" if estimated_plan else "剩余时间")
        st.markdown(
            f"<div class='peer-timer-text'>{format_seconds(remaining)}</div>",
            unsafe_allow_html=True,
        )

    plan = update_manual_plan(state, plan)
    total_minutes = sum(task["minutes"] for task in plan)
    if total_minutes == 20:
        st.caption("总计 20 分钟，同伴按计划倒计时。")
    else:
        st.warning(f"当前总计 {total_minutes} 分钟，建议调整为 20 分钟。")

    progress_cols = st.columns([2, 1])
    progress_cols[0].markdown("任务完成率")
    progress_cols[1].markdown(f"**{int(progress * 100)}%**")
    st.progress(progress)

    button_cols = st.columns(2)
    if timer.get("running"):
        if button_cols[0].button("暂停计时", use_container_width=True):
            pause_timer()
            st.rerun()
    else:
        if button_cols[0].button("开始计时", use_container_width=True):
            start_timer()
            st.rerun()
    if button_cols[1].button("进入下一任务", type="primary", use_container_width=True):
        advance_timer_task(state, reason="manual")
        st.rerun()

    st.markdown(
        (
            "<div class='peer-debug-row'>"
            "<span class='peer-debug-label'>调试次数</span>"
            f"<span class='peer-debug-value'>{int(state.get('debug_count', 0))}</span>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_peer_monitor_area(state):
    with st.container(key="peer_monitor_fixed"):
        st.markdown(f"<div class='peer-monitor-title'>{PEER_MONITOR_TITLE}</div>", unsafe_allow_html=True)
        render_timer_panel(state)


@st.cache_data
def load_avatar_svg(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def chat_avatar(role, agent=None):
    path = CHAT_AVATARS["user"] if role == "user" else CHAT_AVATARS.get(agent)
    if path:
        svg = load_avatar_svg(path)
        if svg:
            return svg
    return ":material/smart_toy:"


def looks_like_inline_python_code(line):
    return (
        "print(" in line
        and line.count("print(") >= 2
        and ("input(" in line or " if " in line or " elif " in line or " else:" in line)
    )


def format_inline_python_code(line):
    normalized = re.sub(
        r"\s+(?=(?:print\(|[A-Za-z_]\w*\s*=\s*input\(|if\s+|elif\s+|else:|for\s+|while\s+))",
        "\n",
        line.strip(),
    )
    formatted_lines = []
    indent_next = 0
    for raw_line in normalized.splitlines():
        code_line = raw_line.strip()
        if not code_line:
            continue
        if re.match(r"^(elif\b|else:)", code_line):
            indent_next = 0
        formatted_lines.append(" " * indent_next + code_line)
        if re.match(r"^(if\b|elif\b|else:|for\b|while\b)", code_line) and code_line.endswith(":"):
            indent_next = 4
    return "```python\n" + "\n".join(formatted_lines) + "\n```"


def format_ai_message(message):
    if "```" in message:
        return message
    lines = []
    for line in (message or "").splitlines():
        if looks_like_inline_python_code(line):
            lines.append(format_inline_python_code(line))
        else:
            lines.append(line)
    return format_quiz_layout("\n".join(lines).strip())


def format_quiz_layout(message):
    if not message:
        return message
    formatted_lines = []
    for raw_line in message.splitlines():
        line = raw_line.strip()
        if not line:
            formatted_lines.append("")
            continue
        line = re.sub(r"\s+([A-D][.．])\s*", r"\n\1 ", line)
        line = re.sub(r"(?<!^)(\n?)(\d+[.．])\s+", r"\n\n\2 ", line)
        formatted_lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(formatted_lines)).strip()


def plan_summary(plan):
    return "，".join(f"{task['name']}{task['minutes']}分钟" for task in plan)


def append_auto_agent_message(state, agent, trigger_message, phase):
    response = call_llm(state, agent, trigger_message)
    response = format_ai_message(clean_reply(response))
    state["conversation"].append({"role": "assistant", "content": response, "agent": agent, "phase": phase})
    saved = save_interaction(
        state,
        agent,
        f"[系统自动调用] {trigger_message}",
        response,
        phase,
        {"auto_triggered": True, "trigger": trigger_message},
    )
    return {"agent": agent, "message": response, "saved": saved}


def append_fixed_agent_message(state, agent, response, phase, trigger):
    response = format_ai_message(clean_reply(response))
    state["conversation"].append({"role": "assistant", "content": response, "agent": agent, "phase": phase})
    saved = save_interaction(
        state,
        agent,
        f"[系统自动提醒] {trigger}",
        response,
        phase,
        {"auto_triggered": True, "trigger": trigger},
    )
    return {"agent": agent, "message": response, "saved": saved}


def auto_continue_after_plan_sync(state, metadata):
    if not metadata.get("plan_synced_to_peer"):
        return []

    plan = active_time_plan(state)
    summary = plan_summary(plan)
    total_minutes = sum(task["minutes"] for task in plan)
    phase = state.get("learning_phase", "IPO问题分析")

    peer_message = (
        f"助教已将学生的学习计划同步给你：{summary}，总计{total_minutes}分钟。"
        "请你作为编程同伴智能体，用两三句话确认会按这个计划监督倒计时和任务进度，"
        "不要进行IPO分析或代码指导。"
    )
    mentor_message = (
        f"学生已经完成时间分配：{summary}，总计{total_minutes}分钟。"
        "请你作为编程导师智能体，立即开始第一个任务“分析问题”，"
        "用IPO模式引导学生说出输入、处理、输出。先提问，不要直接给完整答案。"
    )

    auto_messages = [
        append_auto_agent_message(state, "peer", peer_message, phase),
        append_auto_agent_message(state, "mentor", mentor_message, phase),
    ]
    metadata["auto_messages"] = auto_messages
    metadata["mentor_auto_started"] = True
    metadata["rerun_after_plan_sync"] = True
    return auto_messages


def looks_like_task_completion(message):
    text = re.sub(r"\s+", "", message or "")
    if not text:
        return False
    if any(word in text for word in COMPLETION_WORDS):
        return True
    return bool(re.search(r"(第[一二三四1-4]个)?任务.*(完成|做完|结束)", text))


def auto_advance_after_completion(state, user_message, metadata):
    if not has_estimated_time_plan(state) or metadata.get("complete_timer"):
        return None
    if not looks_like_task_completion(user_message):
        return None

    advanced = advance_timer_task(state, reason="student_completion")
    if not advanced:
        return None

    state["overtime_replan_pending"] = False
    phase = state.get("learning_phase", "任务执行")
    if advanced["all_done"]:
        message = (
            f"我看到你已经完成“{advanced['completed_task']}”。四项任务都已完成，我已帮你暂停倒计时，"
            "接下来可以进入学习自评与报告。"
        )
    else:
        message = (
            f"我看到你已经完成“{advanced['completed_task']}”，已自动帮你进入下一任务："
            f"“{advanced['next_task']}”。继续保持节奏，我会在右侧帮你看着时间。"
        )
    metadata["timer_auto_advanced"] = True
    metadata["rerun_after_timer_update"] = True
    return append_fixed_agent_message(state, "peer", message, phase, "学生完成任务后自动进入下一任务")


def maybe_prompt_overtime(state):
    plan = active_time_plan(state)
    timer = timer_state()
    if not has_estimated_time_plan(state) or not plan or not timer.get("running"):
        return None

    current_index, current_task = current_timer_task(plan, timer)
    completed = int(timer.get("completed_tasks", 0))
    if completed > current_index or current_task_remaining_seconds(plan, timer) > 0:
        return None

    notice_key = f"{int(st.session_state.get('time_plan_version', 0))}:{current_index}:{completed}"
    if timer.get("overtime_notice_key") == notice_key:
        return None

    pause_timer()
    timer = timer_state()
    timer["overtime_notice_key"] = notice_key
    state["overtime_replan_pending"] = True
    remaining_tasks = plan[current_index:]
    remaining_summary = "，".join(f"{task['name']}{task['minutes']}分钟" for task in remaining_tasks)
    message = (
        f"“{current_task['name']}”的预估时间已经用完了。你现在完成了吗？\n\n"
        "如果已经完成，请直接回复“已完成”，我会自动帮你进入下一任务。\n\n"
        f"如果还没有完成，请告诉我是否需要重新分配剩余学习时间。可以直接回复新的安排，例如：{remaining_summary}。"
    )
    return append_fixed_agent_message(state, "peer", message, state.get("learning_phase", "任务执行"), "当前任务超时")


def maybe_refresh_running_timer(state):
    plan = active_time_plan(state)
    timer = timer_state()
    remaining = remaining_timer_seconds(plan, timer)
    if maybe_prompt_overtime(state):
        st.rerun()
    if timer.get("running") and remaining > 0:
        time.sleep(1)
        st.rerun()
    if timer.get("running") and remaining <= 0:
        pause_timer()
        st.rerun()


def handle_chat(message, explicit_agent):
    state = student_state()
    prepare_step_for_prompt(state, message)
    agent = route_agent(message, state, explicit_agent)
    if agent == "manager":
        response = manager_refusal()
        phase = state.get("learning_phase", "准备")
        metadata = {"rejected_by_manager": True}
    else:
        response = call_llm(state, agent, message)
        response, phase, metadata = decorate_message(state, agent, response, message)
        response = maybe_append_auto_followup(state, agent, response, metadata)
        response = clean_reply(response)
        response = format_ai_message(response)
        metadata["routed_by_manager"] = True

    if metadata.get("plan_synced_to_peer") and metadata.get("start_timer"):
        metadata["delay_timer_start"] = True
    sync_timer_from_metadata(metadata)
    state["conversation"].append({"role": "user", "content": message})
    state["conversation"].append({"role": "assistant", "content": response, "agent": agent, "phase": phase})
    auto_continue_after_plan_sync(state, metadata)
    auto_advance_after_completion(state, message, metadata)
    sync_timer_task_from_learning_step(state, metadata)
    if metadata.pop("delay_timer_start", False):
        start_timer()
    metadata["saved"] = save_interaction(state, agent, message, response, phase, metadata)
    return agent, response, phase, metadata


def render_student_page():
    state = student_state()
    inject_student_page_styles()
    st.title("编程自主学习伙伴")

    with st.sidebar:
        st.subheader("学习状态")
        name = st.text_input("学生姓名", value=state.get("student_name", ""), max_chars=30)
        state["student_name"] = name.strip()
        st.metric("当前阶段", state.get("learning_phase", "主题作品体验"))
        selected_agent = st.selectbox("智能体", list(agent_options().keys()), index=0)
        if st.button("重新开始学习", use_container_width=True):
            st.session_state.pop("student_state", None)
            reset_time_plan_session()
            reset_timer()
            st.rerun()

    if not os.getenv("DEEPSEEK_API_KEY"):
        st.warning("尚未配置 DeepSeek API Key。部署到 Streamlit 后，请在 App Secrets 中设置 DEEPSEEK_API_KEY。")

    chat_col, monitor_col = st.columns([2.45, 1.25], gap="large")

    prompt = st.chat_input("输入你的编程学习问题")
    if prompt:
        with chat_col:
            with st.spinner("智能体正在思考..."):
                _, _, _, metadata = handle_chat(prompt.strip(), agent_options()[selected_agent])
                if metadata.get("rerun_after_plan_sync") or metadata.get("rerun_after_timer_update"):
                    st.rerun()
        st.rerun()

    with chat_col:
        with st.container(key="chat_scroll_area"):
            for item in state.get("conversation", []):
                with st.chat_message(item["role"], avatar=chat_avatar(item["role"], item.get("agent"))):
                    if item["role"] == "assistant" and item.get("agent"):
                        st.caption(agent_notice(item["agent"]))
                    st.markdown(item["content"])

    with monitor_col:
        render_peer_monitor_area(state)

    maybe_refresh_running_timer(state)


def save_uploaded_file(uploaded_file):
    if not uploaded_file:
        return False, "请选择要上传的资料。"
    if not allowed_file(uploaded_file.name):
        return False, "文件类型不支持，请上传 pdf、ppt、pptx、doc、docx、txt 或 md。"

    content = uploaded_file.getvalue()
    if not content:
        return False, "上传文件为空，请检查文件内容。"

    original = secure_name(uploaded_file.name)
    ext = original.rsplit(".", 1)[1].lower()
    saved = f"{int(time.time())}_{uuid4().hex}.{ext}"
    upload_dir = choose_upload_dir()
    saved_path = upload_dir / saved
    saved_path.write_bytes(content)

    try:
        knowledge_summary = build_knowledge_summary(extract_text(saved_path))
    except Exception as exc:
        knowledge_summary = f"暂未提取到可读文本，请根据文件名和学生题干判断知识点。提取错误：{exc}"

    execute(
        """
        INSERT INTO knowledge_files
        (original_name, saved_name, file_type, knowledge_summary, uploaded_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (original, saved, ext, knowledge_summary, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    return True, f"已上传：{original}"


def interactions_as_json():
    rows = db_rows("SELECT * FROM interactions ORDER BY created_at ASC")
    return json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")


def interactions_as_csv():
    rows = db_rows("SELECT * FROM interactions ORDER BY created_at ASC")
    output = StringIO()
    fieldnames = [
        "id",
        "session_id",
        "student_name",
        "agent",
        "user_message",
        "assistant_message",
        "phase",
        "metadata",
        "created_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def render_login():
    st.subheader("教师登录")
    with st.form("teacher_login"):
        username = st.text_input("账号")
        password = st.text_input("密码", type="password")
        submitted = st.form_submit_button("登录", use_container_width=True)
    if submitted:
        expected_username = os.getenv("TEACHER_USERNAME", "teacher")
        expected_password = os.getenv("TEACHER_PASSWORD", "123456")
        if username == expected_username and password == expected_password:
            st.session_state["teacher_logged_in"] = True
            st.rerun()
        st.error("账号或密码不正确。")


def render_teacher_page():
    if not st.session_state.get("teacher_logged_in"):
        render_login()
        return

    st.title("教师端")
    if st.button("退出登录"):
        st.session_state["teacher_logged_in"] = False
        st.rerun()

    upload_col, data_col = st.columns([1, 1])
    with upload_col:
        st.subheader("知识库")
        uploaded_file = st.file_uploader("上传资料", type=["pdf", "ppt", "pptx", "doc", "docx", "txt", "md"])
        if st.button("保存到知识库", type="primary", use_container_width=True):
            try:
                ok, message = save_uploaded_file(uploaded_file)
                st.success(message) if ok else st.error(message)
            except Exception as exc:
                st.error(f"上传失败：{exc}")

        files = existing_upload_rows()
        if files:
            st.dataframe(
                [{k: row[k] for k in ["id", "original_name", "file_type", "uploaded_at"]} for row in files],
                use_container_width=True,
                hide_index=True,
            )
            file_id = st.selectbox("选择要删除的文件", [row["id"] for row in files], format_func=lambda value: next(row["original_name"] for row in files if row["id"] == value))
            if st.button("删除所选文件", use_container_width=True):
                delete_knowledge_file(file_id)
                st.rerun()
        else:
            st.info("暂无知识库文件。")

    with data_col:
        st.subheader("学习数据")
        rows = db_rows("SELECT * FROM interactions ORDER BY created_at DESC LIMIT 50")
        st.download_button("下载 CSV", interactions_as_csv(), file_name="interactions.csv", mime="text/csv", use_container_width=True)
        st.download_button("下载 JSON", interactions_as_json(), file_name="interactions.json", mime="application/json", use_container_width=True)
        if st.button("清空学习数据和知识库", use_container_width=True):
            clear_data()
            st.rerun()
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("暂无学习记录。")


def delete_knowledge_file(file_id):
    rows = db_rows("SELECT * FROM knowledge_files WHERE id = ?", (file_id,))
    if not rows:
        return
    row = rows[0]
    upload_path = find_upload_file(row["saved_name"])
    if upload_path:
        upload_path.unlink(missing_ok=True)
    execute("DELETE FROM knowledge_files WHERE id = ?", (file_id,))


def clear_data():
    execute("DELETE FROM interactions")
    execute("DELETE FROM knowledge_files")
    for path in iter_upload_files():
        try:
            path.unlink()
        except OSError:
            pass
    st.session_state.pop("student_state", None)


initialize_app()

page = st.sidebar.radio("页面", ["学生端", "教师端"], horizontal=True)
if page == "学生端":
    render_student_page()
else:
    render_teacher_page()
