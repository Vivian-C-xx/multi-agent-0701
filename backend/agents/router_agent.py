from backend.agents import mentor_agent, peer_agent, tutor_agent
from backend.services.learning_flow import looks_like_debug_success, looks_like_replan, looks_like_time_plan
from backend.utils import contains_any

AGENT_NAMES = {
    "manager": "编程自主学习管家",
    "assistant": "编程助教智能体",
    "mentor": "编程导师智能体",
    "peer": "编程同伴智能体",
}

PROGRAMMING_RELATED_KEYWORDS = [
    "编程", "程序", "代码", "算法", "调试", "报错", "错误", "bug", "python", "scratch",
    "变量", "循环", "条件", "函数", "列表", "字典", "输入", "输出", "流程图", "IPO",
    "学习", "计划", "前测", "测试", "作品", "自评", "评价", "任务", "倒计时", "超时",
    "分析问题", "设计算法", "编写程序", "代码优化", "导师", "助教", "同伴",
    "主题", "游戏", "体验", "掌握", "生活", "题干", "练习", "完成", "全对", "正确率",
    "分支结构", "顺序结构",
]

UNRELATED_KEYWORDS = [
    "天气", "新闻", "电影", "电视剧", "股票", "彩票", "旅游", "菜谱", "做饭",
    "历史", "地理", "物理作业", "英语作文", "语文作文",
]

def is_programming_learning_related(message):
    text = message.lower()
    if "```" in text or "def " in text or "for " in text or "print(" in text or "console.log" in text:
        return True
    if any(k.lower() in text for k in PROGRAMMING_RELATED_KEYWORDS):
        return True
    if any(k in message for k in ["你好", "您好", "开始", "继续", "下一步", "没完成", "不会", "帮我", "掌握", "我已完成"]):
        return not any(k in message for k in UNRELATED_KEYWORDS)
    return False

def manager_refusal():
    return (
        "我是编程自主学习管家，只负责判断你的编程学习意图并分发给合适的智能体。"
        "这个问题和编程学习关系不大，我就不展开回答啦。"
        "你可以把问题改成编程学习相关内容，比如代码报错、算法思路、学习计划或作品优化。"
    )

def agent_notice(agent):
    return f"当前由【{AGENT_NAMES[agent]}】与你对话"

def route_agent(message, state, explicit_agent="auto"):
    text = message.lower()
    step = state.get("learning_step", "topic_intro")
    if step == "self_evaluation":
        return "assistant"
    if explicit_agent in AGENT_NAMES:
        return explicit_agent
    if not is_programming_learning_related(message) and any(k in message for k in UNRELATED_KEYWORDS):
        return "manager"
    if not is_programming_learning_related(message) and step == "topic_intro":
        return "manager"
    if contains_any(message, ["学习完", "学完", "本节课结束", "完成相关内容", "请生成报告", "自评"]):
        return "assistant"
    if looks_like_debug_success(message):
        return "peer"
    if state.get("overtime_replan_pending") and looks_like_time_plan(message):
        return "peer"
    if looks_like_replan(message):
        return "peer"
    if any(k in message for k in ["调试", "报错", "第几行", "运行错误", "Traceback", "SyntaxError", "TypeError", "NameError"]):
        return "mentor"
    if any(k in message for k in ["倒计时", "超时", "没完成", "未完成", "时间已到", "时间到了", "倒计时已结束", "鼓励", "坚持", "剩余时间"]):
        return "peer"
    if tutor_agent.should_handle_step(step):
        return "assistant"
    if mentor_agent.should_handle_step(step):
        return "mentor"
    if peer_agent.should_handle_step(step):
        return "peer"
    if any(k in message for k in ["流程图", "IPO", "输入", "输出", "处理"]):
        return "mentor"
    if any(k in message for k in ["评价", "报告", "学习计划", "计划", "前测", "测试", "作品", "体验"]):
        return "assistant"
    if mentor_agent.looks_like_code(text):
        return "mentor"
    return "assistant"
