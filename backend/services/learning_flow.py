import re

from backend.services.llm_client import call_llm
from backend.utils import contains_any

TASK_PATTERNS = [
    ("分析问题", ["问题分析", "分析问题", "需求分析"]),
    ("设计算法", ["设计算法", "算法设计", "算法"]),
    ("编写程序", ["编写程序", "程序编写", "代码编写", "写代码", "编程"]),
    ("代码优化", ["代码优化", "优化代码", "优化"]),
]

REPLAN_WORDS = ["重新分配", "调整时间", "剩余时间", "再分配", "重置时间"]
DEBUG_SUCCESS_WORDS = ["调试成功", "运行成功", "没有报错", "无报错", "代码成功", "成功了", "问题解决"]

AGENT_LABELS = "编程自主学习管家|编程助教智能体|编程导师智能体|编程同伴智能体"
AGENT_LABEL_RE = re.compile(
    rf"(?:^|\n)\s*(?:[【\[]\s*(?:{AGENT_LABELS})\s*[】\]]\s*[:：]?|(?:{AGENT_LABELS})\s*[:：])\s*"
)


def strip_agent_labels(message):
    cleaned = message or ""
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = AGENT_LABEL_RE.sub("\n", cleaned)
    return cleaned.strip()


def soften_reply_format(message):
    parts = re.split(r"(```.*?```)", message or "", flags=re.S)
    cleaned_parts = []
    for part in parts:
        if part.startswith("```") and part.endswith("```"):
            cleaned_parts.append(part)
            continue
        part = re.sub(r"(?m)^\s*[-*_]{3,}\s*$\n?", "", part)
        part = re.sub(r"(?m)^\s*#{1,6}\s*", "", part)
        part = re.sub(r"(?m)^\s*[*+-]\s+", "", part)
        part = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", part)
        part = re.sub(r"(?m)^\s*>\s*", "", part)
        cleaned_parts.append(part)
    return "".join(cleaned_parts).strip()


def clean_reply(message):
    return soften_reply_format(strip_agent_labels(message))


def parse_time_plan(message):
    text = message.strip()
    planned = {}
    for canonical, aliases in TASK_PATTERNS:
        alias_group = "|".join(re.escape(alias) for alias in aliases)
        patterns = [
            rf"({alias_group})\s*[：:、，,\s]*([1-9]\d*)\s*分钟",
            rf"([1-9]\d*)\s*分钟\s*(?:的)?\s*({alias_group})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            values = [group for group in match.groups() if group and group.isdigit()]
            if values:
                planned[canonical] = int(values[0])
                break
    return [{"name": name, "minutes": planned[name]} for name, _ in TASK_PATTERNS if name in planned]

def looks_like_time_plan(message):
    parsed_tasks = parse_time_plan(message)
    if len(parsed_tasks) >= 2:
        return True
    task_words = ["分析", "算法", "编程", "优化", "分钟"]
    if not contains_any(message, task_words):
        return False
    if "20" in message or "总计" in message or "一共" in message:
        return True
    minutes = [int(value) for value in re.findall(r"(\d+)\s*分钟", message)]
    return len(minutes) >= 4 and sum(minutes[:4]) == 20

def looks_like_replan(message):
    return contains_any(message, REPLAN_WORDS) and bool(parse_time_plan(message))

def looks_like_debug_success(message):
    return contains_any(message, DEBUG_SUCCESS_WORDS)

def assistant_confirms_quiz_pass(message):
    text = re.sub(r"\s+", "", message or "").replace("％", "%")
    if not text:
        return False
    negative_patterns = [
        r"前测通过[:：]?否",
        r"正确率[:：]?(?!100%)\d{1,2}%",
        r"未(?:达到|达)100%",
        r"没有(?:达到)?100%",
        r"还(?:没|未)有?全[部都]?答对",
        r"不能进入(?:任务拆解|时间分配|下一阶段)",
    ]
    if any(re.search(pattern, text) for pattern in negative_patterns):
        return False
    pass_patterns = [
        r"前测通过[:：]?是",
        r"正确率[:：]?100%",
        r"得分[:：]?100%",
        r"全部答对",
        r"全都答对",
        r"可以进入(?:任务拆解|时间分配|下一阶段)",
    ]
    return any(re.search(pattern, text) for pattern in pass_patterns)

def prepare_step_for_prompt(state, user_message):
    step = state.get("learning_step", "topic_intro")
    text = user_message.strip()
    if step == "quiz_explain_wait" and contains_any(text, ["掌握", "明白", "懂了", "会了"]):
        state["learning_phase"] = "掌握检验"
        state["learning_step"] = "quiz_review"

def update_learning_step(state, agent, user_message, assistant_message=""):
    step = state.get("learning_step", "topic_intro")
    phase = state.get("learning_phase", "主题作品体验")
    text = user_message.strip()
    metadata = {}

    if agent == "assistant" and step == "plan_allocation" and looks_like_time_plan(text):
        planned_tasks = parse_time_plan(text)
        phase = "IPO问题分析"
        step = "ipo_analysis"
        state["plan_synced"] = True
        if planned_tasks:
            state["time_plan"] = planned_tasks
        metadata["start_timer"] = True
        metadata["plan_synced_to_peer"] = True
        metadata["time_plan"] = planned_tasks
        metadata["total_minutes"] = sum(task["minutes"] for task in planned_tasks)
    elif agent == "peer" and (state.get("overtime_replan_pending") or looks_like_replan(text)) and looks_like_time_plan(text):
        planned_tasks = parse_time_plan(text)
        if planned_tasks:
            state["time_plan"] = planned_tasks
        state["overtime_replan_pending"] = False
        metadata["reset_timer"] = True
        metadata["start_timer"] = True
        metadata["time_plan"] = planned_tasks
        metadata["total_minutes"] = sum(task["minutes"] for task in planned_tasks)
    elif agent == "peer" and looks_like_debug_success(text):
        phase = "学习自评与报告"
        step = "self_evaluation"
        metadata["complete_timer"] = True
        metadata["pause_timer"] = True
        metadata["progress"] = 100
    elif step == "topic_intro" and agent == "assistant":
        state["current_topic"] = text[:80]
        phase = "主题作品体验"
        step = "experience_feedback"
    elif step == "experience_feedback" and contains_any(text, ["我已完成体验", "完成体验", "已体验", "体验完成"]):
        phase = "生活迁移思考"
        step = "life_connection"
    elif step == "life_connection" and agent == "assistant":
        phase = "练习题干输入"
        step = "exercise_intake"
    elif step == "exercise_intake" and agent == "assistant":
        state["exercise_prompt"] = text[:500]
        phase = "前测"
        step = "quiz"
    elif step == "quiz" and agent == "assistant":
        if assistant_confirms_quiz_pass(assistant_message):
            phase = "任务拆解与时间分配"
            step = "plan_allocation"
            metadata["quiz_passed"] = True
        else:
            phase = "前测讲解"
            step = "quiz_explain_wait"
            metadata["quiz_passed"] = False
    elif step == "quiz_review" and agent == "assistant":
        phase = "掌握检验"
        step = "quiz"
    elif step == "quiz_explain_wait" and agent == "assistant":
        phase = "前测讲解"
        step = "quiz_explain_wait"
    elif step == "ipo_analysis" and contains_any(text, ["IPO正确", "分析正确", "完全正确", "结束问题分析"]):
        phase = "流程图完善"
        step = "flowchart"
    elif step == "flowchart" and contains_any(text, ["流程图正确", "流程图完成", "完全正确", "代码写完", "编写完代码"]):
        phase = "代码编写与调试"
        step = "debugging"
    elif contains_any(text, ["报错", "错误", "bug", "调试", "Traceback", "SyntaxError", "TypeError", "NameError"]):
        phase = "代码编写与调试"
        step = "debugging"
    elif contains_any(text, ["学习完", "学完", "本节课结束", "完成相关内容", "请生成报告", "自评"]):
        phase = "学习自评与报告"
        step = "self_evaluation"

    state["learning_phase"] = phase
    state["learning_step"] = step
    metadata["learning_step"] = step
    return phase, metadata

def decorate_message(state, agent, message, user_message):
    phase = state.get("learning_phase", "准备")
    message = clean_reply(message)
    next_phase, metadata = update_learning_step(state, agent, user_message, message)
    phase = next_phase
    debug_words = ["调试", "报错", "错误", "代码", "bug", "Bug", "BUG", "Traceback", "SyntaxError", "TypeError", "NameError"]
    if agent == "mentor" and any(k in user_message for k in debug_words):
        state["debug_count"] = int(state.get("debug_count", 0)) + 1
        metadata["debug_count"] = state["debug_count"]
        if state["debug_count"] >= 2:
            peer_message = (
                "学生已经连续调试了好几次。请你作为编程同伴智能体，先用简短、真诚的话鼓励学生，"
                "肯定他正在认真排查，再提醒他跟着导师继续缩小问题范围。"
            )
            peer_response = call_llm(state, "peer", peer_message)
            metadata["before_messages"] = [{"agent": "peer", "message": clean_reply(peer_response)}]
            metadata["peer_encouraged_before_debug"] = True
    if metadata.get("plan_synced_to_peer"):
        total_minutes = metadata.get("total_minutes") or 20
        message += (
            f"\n\n学习计划已同步给编程同伴智能体。右侧计时器将按你分配的{total_minutes}分钟自动开始；"
            "接下来由编程导师智能体引导你完成IPO分析。每完成一个任务，直接告诉我“已完成”即可，"
            "同伴智能体会自动进入下一任务；你也可以使用右侧“进入下一任务”按钮手动推进。"
        )
    if agent == "peer" and any(k in user_message for k in ["没完成", "未完成", "超时", "时间已到", "倒计时已结束"]):
        metadata["overtime"] = True
        state["overtime_replan_pending"] = True
        message += (
            "\n\n请先停一下，重新分析这项任务为什么超时：是任务拆得太大、分析卡住、还是时间估计偏短。"
            "请直接回复剩余任务的新时间安排，例如“设计算法3分钟，编写程序6分钟，代码优化6分钟”。"
            "我会把右侧倒计时重置为新的剩余计划，并从第一项剩余任务开始计时。"
        )
    if agent == "peer" and metadata.get("reset_timer"):
        total_minutes = metadata.get("total_minutes") or 0
        message += f"\n\n新的剩余时间计划已同步到右侧倒计时，总计{total_minutes}分钟，现在重新开始计时。"
    if agent == "peer" and metadata.get("complete_timer"):
        message += "\n\n我已经帮你暂停倒计时，并把任务完成率更新到100%。接下来可以请助教带你做学习评价。"
    return clean_reply(message), phase, metadata

def maybe_append_auto_followup(state, agent, response, metadata):
    return clean_reply(response)
