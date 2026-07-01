# 系统文件结构说明

本项目是面向初中生编程自主学习的“1+3”多智能体系统原型。“1”指入口智能体“编程自主学习管家”，负责识别学生意图并分发任务；“3”指编程助教智能体、编程导师智能体和编程同伴智能体，分别承担计划评价、编程指导和过程陪伴职责。

## 当前目录结构

```text
project/
  app.py
  backend/
    main.py
    server.py
    config.py
    storage.py
    upload_store.py
    utils.py
    agents/
      router_agent.py
      tutor_agent.py
      mentor_agent.py
      peer_agent.py
      prompt_builder.py
    services/
      learning_flow.py
      knowledge_base.py
      llm_client.py
  templates/
    index.html
    student.html
    teacher.html
    teacher_login.html
  static/
    styles.css
    student.js
  data/
    app.db
  uploads/
  uploaded_knowledge/
  .env.example
  .gitignore
  requirements.txt
  README.md
```

## 核心文件说明

- `app.py`：项目启动入口，调用 `backend.main.main()`，便于在项目根目录执行 `python app.py`。
- `backend/main.py`：后端服务启动文件，加载环境变量、初始化存储，并启动本地 HTTP 服务。
- `backend/server.py`：HTTP 请求处理器，负责页面路由、学生聊天接口、教师登录、知识库上传、数据导出和数据清理等 Web 控制逻辑。
- `backend/config.py`：集中定义项目根目录、模板目录、静态资源目录、数据目录、上传目录、模型接口默认配置等基础配置。
- `backend/storage.py`：SQLite 数据库初始化与读写封装，保存学生学习过程记录和知识库文件记录。
- `backend/upload_store.py`：上传目录选择、可写性检测、上传文件查找与遍历。
- `backend/utils.py`：环境变量读取、模板读取、文件名清洗、学生会话状态初始化等通用工具函数。

## 智能体模块说明

- `backend/agents/router_agent.py`：入口智能体逻辑，判断输入是否属于编程学习场景，并将任务分发给助教、导师或同伴智能体。
- `backend/agents/tutor_agent.py`：编程助教智能体的阶段归属定义，主要对应主题体验、前测、计划制定和学习评价。
- `backend/agents/mentor_agent.py`：编程导师智能体的阶段归属定义，主要对应 IPO 分析、流程图完善和代码调试。
- `backend/agents/peer_agent.py`：编程同伴智能体的阶段归属定义，主要对应学习进度监控、倒计时提醒、超时重规划和鼓励反馈。
- `backend/agents/prompt_builder.py`：根据当前学习阶段和智能体角色生成系统提示词，是智能体行为约束的主要集中位置。

## 服务模块说明

- `backend/services/learning_flow.py`：维护学习流程状态，包括前测通过判断、时间计划解析、阶段流转、调试次数统计、倒计时元数据生成等。
- `backend/services/knowledge_base.py`：处理教师上传知识库文件的文本抽取、摘要截取和近期知识库上下文拼接。
- `backend/services/llm_client.py`：封装 DeepSeek Chat Completions 接口调用，并处理鉴权、网络、超时和 HTTP 错误提示。

## 前端与页面文件说明

- `templates/index.html`：系统统一入口页面，提供学生端和教师端入口。
- `templates/student.html`：学生端学习界面，包含智能体状态、聊天区、学习计时与任务进度区。
- `templates/teacher.html`：教师端管理界面，包含知识库上传、上传记录展示、学习数据下载与清理入口。
- `templates/teacher_login.html`：教师登录页面。
- `static/styles.css`：学生端与教师端共用样式。
- `static/student.js`：学生端交互逻辑，负责聊天请求、智能体状态显示、计时器、任务进度和前端学习流程反馈。

## 数据与运行产物说明

- `data/app.db`：SQLite 运行数据库，保存学习过程记录和知识库文件元数据。该文件由程序运行生成，不建议提交到版本库。
- `uploads/`：教师端上传资料的主要保存目录。该目录属于运行数据，不建议提交到版本库。
- `uploaded_knowledge/`：历史或兼容上传目录，当前上传目录不可写时可作为候选目录之一。该目录也属于运行数据，不建议提交到版本库。
- `__pycache__/`：Python 字节码缓存目录，由解释器自动生成，不属于源代码。
- `.venv/`：本地虚拟环境目录，不属于项目源代码。
- `.idea/`：本地 IDE 配置目录，不属于项目源代码。

## 建议的后续结构优化

当前项目已经完成了 `backend/agents/` 与 `backend/services/` 的初步拆分，但 `backend/server.py` 仍然承担较多职责。后续可在不改变接口行为的前提下，逐步拆分为：

```text
backend/
  database/
    db.py
  services/
    session_service.py
    record_service.py
    knowledge_service.py
    timer_service.py
  models/
    schemas.py
    learning_state.py
```

建议优先拆分数据库读写、知识库上传、学习记录导出和会话状态管理，最后再处理 Web 路由层。这样可以降低一次性重构风险，并保持现有学生端和教师端功能稳定。
