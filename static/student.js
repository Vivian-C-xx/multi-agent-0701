const chatLog = document.querySelector("#chatLog");
const chatForm = document.querySelector("#chatForm");
const messageInput = document.querySelector("#messageInput");
const chips = document.querySelectorAll(".agent-chip");
const studentName = document.querySelector("#studentName");
const activeAgentName = document.querySelector("#activeAgentName");
const timerTask = document.querySelector("#timerTask");
const timerClock = document.querySelector("#timerClock");
const debugCount = document.querySelector("#debugCount");
const progressText = document.querySelector("#progressText");
const progressBar = document.querySelector("#progressBar");
const pauseTimerButton = document.querySelector("#pauseTimer");
const nextTaskButton = document.querySelector("#nextTask");
const timePlanHint = document.querySelector("#timePlanHint");

let timer = null;
let timerStarted = false;
let taskIndex = 0;
let secondsLeft = 20 * 60;
let tasks = readTasks();
let activeTasks = null;

const agentLabels = [
  "编程自主学习管家",
  "编程助教智能体",
  "编程导师智能体",
  "编程同伴智能体",
];

function readTasks() {
  return [...document.querySelectorAll(".time-inputs input")].map((input) => ({
    name: input.dataset.task,
    minutes: Math.max(1, Number(input.value || 1)),
  }));
}

function totalPlannedMinutes() {
  return (activeTasks || readTasks()).reduce((sum, task) => sum + task.minutes, 0);
}

function renderTimePlanHint() {
  const total = totalPlannedMinutes();
  if (!timePlanHint) return;
  timePlanHint.textContent = `当前总计 ${total} 分钟，同伴会按这个计划倒计时。`;
  timePlanHint.classList.toggle("warning", total <= 0);
}

function setActiveAgent(agent) {
  chips.forEach((chip) => chip.classList.toggle("active", chip.dataset.agent === agent));
}

function addMessage(role, text, agent = "") {
  const node = document.createElement("div");
  node.className = `message ${role} ${agent}`;
  if (role === "user") {
    node.textContent = text;
  } else {
    const title = document.createElement("strong");
    title.textContent = agentName(agent);
    const body = document.createElement("p");
    body.textContent = stripAgentLabels(text);
    node.append(title, body);
  }
  chatLog.appendChild(node);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function stripAgentLabels(text) {
  const labelPattern = agentLabels.join("|");
  const bracketed = new RegExp(`[【\\[]\\s*(?:${labelPattern})\\s*[】\\]]\\s*[:：]?\\s*`, "g");
  const bare = new RegExp(`(?:^|\\n)\\s*(?:${labelPattern})\\s*[:：]\\s*`, "g");
  return String(text || "")
    .replace(bracketed, "")
    .replace(bare, "\n")
    .trim();
}

function agentName(agent) {
  return {
    manager: "编程自主学习管家",
    assistant: "编程助教智能体",
    mentor: "编程导师智能体",
    peer: "编程同伴智能体",
  }[agent] || "智能体";
}

async function sendMessage(message, agent = "auto") {
  addMessage("user", message);
  messageInput.value = "";
  messageInput.disabled = true;
  const waiting = document.createElement("div");
  waiting.className = "message bot";
  waiting.textContent = "正在思考...";
  chatLog.appendChild(waiting);
  chatLog.scrollTop = chatLog.scrollHeight;
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, agent }),
    });
    const text = await res.text();
    const data = text ? JSON.parse(text) : {};
    waiting.remove();
    if (!res.ok) {
      addMessage("bot", data.error || "发送失败，请稍后重试。", "assistant");
      return;
    }
    setActiveAgent(data.agent);
    if (activeAgentName) {
      activeAgentName.textContent = data.agent_name || agentName(data.agent);
    }
    if (debugCount) {
      debugCount.textContent = data.debug_count || 0;
    }
    const metadata = data.metadata || {};
    if (Array.isArray(metadata.before_messages)) {
      metadata.before_messages.forEach((item) => {
        addMessage("bot", item.message || "", item.agent || "assistant");
      });
    }
    addMessage("bot", data.message || "智能体暂时没有返回内容，请再试一次。", data.agent);
    if (metadata.start_timer) {
      applyTimePlan(metadata.time_plan, { replace: Boolean(metadata.reset_timer) });
      startTimer();
    }
    if (metadata.complete_timer) {
      completeTimer();
    }
  } catch (error) {
    waiting.remove();
    addMessage("bot", `请求失败：${error.message || "请检查后端服务是否正常运行。"}`, "assistant");
  } finally {
    messageInput.disabled = false;
    messageInput.focus();
  }
}

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (message) sendMessage(message);
});

function normalizeTimePlan(timePlan) {
  return (Array.isArray(timePlan) ? timePlan : [])
    .map((task) => ({
      name: task.name,
      minutes: Math.max(1, Number(task.minutes || 1)),
    }))
    .filter((task) => task.name && task.minutes > 0);
}

function applyTimePlan(timePlan, options = {}) {
  const normalized = normalizeTimePlan(timePlan);
  if (normalized.length === 0) return;
  const inputs = [...document.querySelectorAll(".time-inputs input")];
  normalized.forEach((task) => {
    const input = inputs.find((item) => item.dataset.task === task.name);
    if (input) input.value = task.minutes;
  });
  clearInterval(timer);
  timer = null;
  timerStarted = false;
  activeTasks = options.replace ? normalized : null;
  taskIndex = 0;
  tasks = activeTasks || readTasks();
  secondsLeft = tasks.length ? tasks[0].minutes * 60 : 0;
  renderTimePlanHint();
  renderTimer();
}

chips.forEach((chip) => {
  chip.type = "button";
});

studentName.addEventListener("change", async () => {
  await fetch("/api/student-name", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: studentName.value.trim() }),
  });
});

document.querySelectorAll(".time-inputs input").forEach((input) => {
  input.addEventListener("change", () => {
    activeTasks = null;
    tasks = readTasks();
    renderTimePlanHint();
    if (!timer) {
      taskIndex = 0;
      secondsLeft = tasks[0].minutes * 60;
      renderTimer();
    }
  });
});

function renderTimer() {
  const task = tasks[taskIndex] || { name: "学习完成", minutes: 0 };
  timerTask.textContent = taskIndex < tasks.length ? `当前任务：${task.name}` : "全部任务已结束";
  const minutes = String(Math.floor(secondsLeft / 60)).padStart(2, "0");
  const seconds = String(secondsLeft % 60).padStart(2, "0");
  timerClock.textContent = `${minutes}:${seconds}`;
  const progress = tasks.length ? Math.min(100, Math.round((taskIndex / tasks.length) * 100)) : 0;
  if (progressText) progressText.textContent = `${progress}%`;
  if (progressBar) progressBar.style.width = `${progress}%`;
  renderTimerButton();
}

function renderTimerButton() {
  if (!pauseTimerButton) return;
  const finished = taskIndex >= tasks.length || secondsLeft <= 0;
  pauseTimerButton.disabled = !timerStarted || finished;
  pauseTimerButton.textContent = timer || !timerStarted ? "暂停计时" : "继续计时";
}

function startTimer() {
  tasks = activeTasks || readTasks();
  if (!tasks.length) return;
  if (taskIndex >= tasks.length) taskIndex = 0;
  if (!secondsLeft || secondsLeft <= 0) secondsLeft = tasks[taskIndex].minutes * 60;
  timerStarted = true;
  renderTimePlanHint();
  renderTimer();
  clearInterval(timer);
  timer = setInterval(() => {
    secondsLeft -= 1;
    renderTimer();
    if (secondsLeft <= 0) {
      clearInterval(timer);
      timer = null;
      renderTimerButton();
      sendMessage(
        `当前任务“${tasks[taskIndex].name}”倒计时已结束，我还没有确认完成，属于超时未完成。请编程同伴智能体监督我重新分析任务时间，并帮我调整接下来的学习节奏。`,
        "peer"
      );
    }
  }, 1000);
  renderTimerButton();
}

function completeTimer() {
  clearInterval(timer);
  timer = null;
  timerStarted = false;
  tasks = activeTasks || readTasks();
  taskIndex = tasks.length;
  secondsLeft = 0;
  renderTimer();
}

function toggleTimerPause() {
  if (timer) {
    clearInterval(timer);
    timer = null;
    renderTimerButton();
    return;
  }
  startTimer();
}

function nextTask() {
  clearInterval(timer);
  timer = null;
  timerStarted = false;
  taskIndex += 1;
  if (taskIndex < tasks.length) {
    secondsLeft = tasks[taskIndex].minutes * 60;
    renderTimer();
    startTimer();
    if (tasks[taskIndex].name === "设计算法") {
      sendMessage("我已经结束问题分析任务，请导师根据我的 IPO 总结生成流程图框架。");
    }
  } else {
    secondsLeft = 0;
    renderTimer();
    sendMessage("我已完成相关知识的学习，请对我的学习进行评价。");
  }
}

pauseTimerButton.addEventListener("click", toggleTimerPause);
nextTaskButton.addEventListener("click", nextTask);
renderTimePlanHint();
renderTimer();
