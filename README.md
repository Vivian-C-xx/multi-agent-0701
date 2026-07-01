# 编程自主学习伙伴

面向初中生编程自主学习的“1+3”多智能体系统原型，包含入口智能体、编程助教智能体、编程导师智能体、编程同伴智能体、学生端、教师端、知识库上传、学习过程记录与学习数据导出。

## Streamlit 运行方式

1. 安装依赖：

```bash
pip install -r requirements.txt
```

2. 创建 `.env` 文件，或在 Streamlit Cloud 的 Secrets 中配置：

```env
DEEPSEEK_API_KEY=你的DeepSeek密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
TEACHER_USERNAME=teacher
TEACHER_PASSWORD=请改成更安全的密码
```

3. 本地启动 Streamlit 版本：

```bash
streamlit run streamlit_app.py
```

Streamlit 版本入口文件是 `streamlit_app.py`，包含学生端对话、教师端登录、知识库上传、学习记录查看与 CSV/JSON 导出。

## Streamlit Cloud 部署

1. 把项目上传到 GitHub。
2. 打开 https://share.streamlit.io 并连接 GitHub 仓库。
3. 选择仓库和 `main` 分支。
4. Main file path 填写：

```text
streamlit_app.py
```

5. 在 Advanced settings 的 Secrets 中填写：

```toml
DEEPSEEK_API_KEY = "你的DeepSeek密钥"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
TEACHER_USERNAME = "teacher"
TEACHER_PASSWORD = "请改成更安全的密码"
```

6. 点击 Deploy。部署成功后，Streamlit 会生成一个 `https://xxx.streamlit.app` 链接。

注意：Streamlit Cloud 的本地 SQLite 数据和上传文件适合原型演示，不适合长期持久化保存。应用重启、重新部署或平台回收资源后，运行数据可能丢失。正式使用建议接入云数据库和对象存储。

## 原 HTTP 版本运行方式

1. 启动项目：

```bash
python app.py
```

2. 如果没有配置密钥，终端会提示：

```text
请输入 DeepSeek API Key:
```

粘贴你的 DeepSeek 密钥后回车即可运行。

也可以提前创建 `.env` 文件：

```env
DEEPSEEK_API_KEY=你的DeepSeek密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

`DEEPSEEK_BASE_URL` 和 `DEEPSEEK_MODEL` 都是可选项；只填写 `DEEPSEEK_API_KEY` 也可以。

3. 访问页面：

- 统一入口：http://127.0.0.1:5000/
- 学生端：http://127.0.0.1:5000/student
- 教师端：http://127.0.0.1:5000/teacher/login

教师端默认账号密码：

- 账号：`teacher`
- 密码：`123456`

可通过环境变量 `TEACHER_USERNAME`、`TEACHER_PASSWORD` 修改。

## 文件说明

- `app.py`：项目根目录启动入口。
- `streamlit_app.py`：Streamlit 部署入口，适用于 Streamlit Community Cloud。
- `backend/main.py`：后端服务启动、环境变量加载和存储初始化。
- `backend/server.py`：HTTP 路由、学生端接口、教师端页面、上传和导出控制。
- `backend/agents/`：入口智能体、助教智能体、导师智能体、同伴智能体和提示词构建逻辑。
- `backend/services/`：学习流程、知识库处理和大模型接口调用。
- `backend/storage.py`：SQLite 数据库初始化和读写封装。
- `templates/`：页面模板。
- `static/`：样式与学生端交互脚本。
- `data/app.db`：运行后自动生成或更新的 SQLite 数据库。
- `uploads/`：教师上传资料的保存目录。
- `.env.example`：DeepSeek API 配置示例。

更完整的结构说明见 `docs/system_file_structure.md`。
