import csv
import json
import os
import time
import urllib.parse
from datetime import datetime
from email.parser import BytesParser
from email.policy import default
from http import cookies
from http.server import BaseHTTPRequestHandler
from io import StringIO
from uuid import uuid4

from backend.agents.router_agent import AGENT_NAMES, agent_notice, manager_refusal, route_agent
from backend.config import SESSIONS, STATIC_DIR
from backend.services.knowledge_base import build_knowledge_summary, existing_upload_rows, extract_text
from backend.services.learning_flow import clean_reply, decorate_message, maybe_append_auto_followup, prepare_step_for_prompt
from backend.services.llm_client import call_llm
from backend.storage import db_rows, execute, save_interaction
from backend.upload_store import choose_upload_dir, find_upload_file, iter_upload_files
from backend.utils import allowed_file, esc, ensure_student_state, read_template, secure_name

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            return self.html(read_template("index.html"))
        if path == "/student":
            ensure_student_state(self.state())
            return self.html(read_template("student.html"))
        if path == "/teacher/login":
            return self.html(read_template("teacher_login.html").replace("{{ERROR}}", ""))
        if path == "/teacher/logout":
            self.state().pop("teacher_logged_in", None)
            return self.redirect("/")
        if path == "/teacher":
            if not self.state().get("teacher_logged_in"):
                return self.redirect("/teacher/login")
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self.html(self.render_teacher(params))
        if path.startswith("/teacher/download/"):
            return self.download(path.rsplit("/", 1)[-1])
        if path.startswith("/static/"):
            return self.static_file(path.removeprefix("/static/"))
        return self.not_found()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/student-name":
            data = self.read_json()
            state = self.state()
            ensure_student_state(state)
            state["student_name"] = data.get("name", "").strip()[:30]
            return self.json({"ok": True})
        if path == "/api/chat":
            try:
                return self.chat()
            except Exception as exc:
                print(f"[ERROR] /api/chat failed: {exc}")
                return self.json({"error": f"chat api failed: {exc}"}, status=500)
        if path == "/teacher/login":
            return self.teacher_login()
        if path == "/teacher/upload":
            try:
                return self.upload_knowledge()
            except Exception as exc:
                print(f"[ERROR] /teacher/upload failed: {exc}")
                return self.redirect("/teacher?upload_error=" + urllib.parse.quote("上传失败，请查看终端日志后重试。"))
        if path == "/teacher/delete-file":
            return self.delete_knowledge_file()
        if path == "/teacher/clear-data":
            return self.clear_data()
        return self.not_found()

    def chat(self):
        state = self.state()
        ensure_student_state(state)
        data = self.read_json()
        message = data.get("message", "").strip()
        if not message:
            return self.json({"error": "请输入学习问题。"}, status=400)
        prepare_step_for_prompt(state, message)
        agent = route_agent(message, state, data.get("agent", "auto"))
        if agent == "manager":
            response = manager_refusal()
            phase = state.get("learning_phase", "准备")
            metadata = {"rejected_by_manager": True}
        else:
            response = call_llm(state, agent, message)
            response, phase, metadata = decorate_message(state, agent, response, message)
            response = maybe_append_auto_followup(state, agent, response, metadata)
            response = clean_reply(response)
            metadata["routed_by_manager"] = True
        state["conversation"].append({"role": "user", "content": message})
        state["conversation"].append({"role": "assistant", "content": response})
        metadata["saved"] = save_interaction(state, agent, message, response, phase, metadata)
        return self.json(
            {
                "agent": agent,
                "agent_name": AGENT_NAMES[agent],
                "agent_notice": agent_notice(agent),
                "message": response,
                "phase": phase,
                "metadata": metadata,
                "debug_count": state.get("debug_count", 0),
            }
        )

    def teacher_login(self):
        form = urllib.parse.parse_qs(self.read_body().decode("utf-8", errors="ignore"))
        username = form.get("username", [""])[0]
        password = form.get("password", [""])[0]
        if username == os.getenv("TEACHER_USERNAME", "teacher") and password == os.getenv("TEACHER_PASSWORD", "123456"):
            self.state()["teacher_logged_in"] = True
            return self.redirect("/teacher")
        page = read_template("teacher_login.html").replace("{{ERROR}}", "账号或密码不正确")
        return self.html(page)

    def upload_knowledge(self):
        if not self.state().get("teacher_logged_in"):
            return self.redirect("/teacher/login")
        content_type = self.headers.get("Content-Type", "")
        body = self.read_body()
        upload = self.parse_multipart_file(content_type, body, "file")
        if not upload:
            return self.redirect("/teacher?upload_error=" + urllib.parse.quote("没有读取到上传文件，请重新选择资料。"))
        filename, content = upload
        if not filename or not allowed_file(filename):
            return self.redirect("/teacher?upload_error=" + urllib.parse.quote("文件类型不支持，请上传 pdf、ppt、pptx、doc、docx、txt 或 md。"))
        if not content:
            return self.redirect("/teacher?upload_error=" + urllib.parse.quote("上传文件为空，请检查文件内容。"))
        original = secure_name(filename)
        ext = original.rsplit(".", 1)[1].lower()
        saved = f"{int(time.time())}_{uuid4().hex}.{ext}"
        try:
            upload_dir = choose_upload_dir()
        except OSError as exc:
            print(f"[WARN] 知识库上传目录不可写：{exc}")
            return self.redirect("/teacher?upload_error=" + urllib.parse.quote("上传目录不可写，请检查 uploads 目录权限，或设置 APP_UPLOAD_DIR。"))
        saved_path = upload_dir / saved
        try:
            saved_path.write_bytes(content)
        except OSError as exc:
            print(f"[WARN] 知识库文件保存失败：{exc}")
            return self.redirect("/teacher?upload_error=" + urllib.parse.quote("文件保存失败，请检查上传目录权限，或设置 APP_UPLOAD_DIR。"))
        try:
            knowledge_summary = build_knowledge_summary(extract_text(saved_path))
        except Exception as exc:
            print(f"[WARN] 知识库文本提取失败：{exc}")
            knowledge_summary = "暂未提取到可读文本，请根据文件名和学生题干判断知识点。"
        execute(
            """
            INSERT INTO knowledge_files
            (original_name, saved_name, file_type, knowledge_summary, uploaded_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (original, saved, ext, knowledge_summary, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        return self.redirect("/teacher?upload_success=" + urllib.parse.quote(f"已上传：{original}"))

    def delete_knowledge_file(self):
        if not self.state().get("teacher_logged_in"):
            return self.redirect("/teacher/login")
        form = urllib.parse.parse_qs(self.read_body().decode("utf-8", errors="ignore"))
        try:
            file_id = int(form.get("file_id", [""])[0])
        except (TypeError, ValueError):
            return self.redirect("/teacher?upload_error=" + urllib.parse.quote("删除失败：文件编号无效。"))

        rows = db_rows("SELECT * FROM knowledge_files WHERE id = ?", (file_id,))
        if not rows:
            return self.redirect("/teacher?upload_error=" + urllib.parse.quote("删除失败：文件记录不存在。"))

        row = rows[0]
        upload_path = find_upload_file(row["saved_name"])
        if upload_path:
            try:
                upload_path.unlink()
            except OSError as exc:
                print(f"[WARN] 知识库文件删除失败：{upload_path}: {exc}")
                return self.redirect("/teacher?upload_error=" + urllib.parse.quote("删除失败：无法删除磁盘文件，请检查目录权限。"))
        execute("DELETE FROM knowledge_files WHERE id = ?", (file_id,))
        return self.redirect("/teacher?upload_success=" + urllib.parse.quote(f"已删除：{row['original_name']}"))

    def parse_multipart_file(self, content_type, body, field_name):
        if "multipart/form-data" not in content_type:
            return None
        raw = (
            f"Content-Type: {content_type}\r\n"
            "MIME-Version: 1.0\r\n\r\n"
        ).encode("utf-8") + body
        message = BytesParser(policy=default).parsebytes(raw)
        if not message.is_multipart():
            return None
        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue
            if part.get_param("name", header="content-disposition") != field_name:
                continue
            filename = part.get_filename()
            content = part.get_payload(decode=True) or b""
            if filename and content:
                return filename, content
        return None

    def clear_data(self):
        if not self.state().get("teacher_logged_in"):
            return self.redirect("/teacher/login")
        execute("DELETE FROM interactions")
        execute("DELETE FROM knowledge_files")
        for path in iter_upload_files():
            try:
                path.unlink()
            except OSError as exc:
                print(f"[WARN] 上传文件删除失败：{path}: {exc}")
        for state in SESSIONS.values():
            state.pop("conversation", None)
            state["debug_count"] = 0
            state["learning_phase"] = "主题作品体验"
            state["learning_step"] = "topic_intro"
            state["current_topic"] = ""
            state["exercise_prompt"] = ""
            state["plan_synced"] = False
            state["time_plan"] = []
        return self.redirect("/teacher")

    def render_teacher(self, params=None):
        page = read_template("teacher.html")
        params = params or {}
        upload_status = ""
        if params.get("upload_error"):
            upload_status = f'<p class="error">{esc(params["upload_error"][0])}</p>'
        elif params.get("upload_success"):
            upload_status = f'<p class="success">{esc(params["upload_success"][0])}</p>'
        files = existing_upload_rows()
        interactions = db_rows("SELECT * FROM interactions ORDER BY created_at DESC LIMIT 50")
        file_rows = "".join(
            "<tr>"
            f"<td>{esc(f['original_name'])}</td>"
            f"<td>{esc(f['file_type'])}</td>"
            f"<td>{esc(f['uploaded_at'])}</td>"
            '<td class="action-col">'
            '<form class="inline-form" action="/teacher/delete-file" method="post" '
            'onsubmit="return confirm(\'确定删除这个文件吗？此操作不可撤销。\');">'
            f'<input type="hidden" name="file_id" value="{esc(f["id"])}">'
            '<button class="danger small" type="submit">删除</button>'
            "</form>"
            "</td>"
            "</tr>"
            for f in files
        ) or '<tr><td colspan="4">暂无文件</td></tr>'
        interaction_rows = "".join(
            "<tr>"
            f"<td>{esc(r['created_at'])}</td><td>{esc(r['student_name'] or '未填写')}</td>"
            f"<td>{esc(r['agent'])}</td><td>{esc(r['phase'])}</td><td>{esc(r['user_message'])}</td>"
            "</tr>"
            for r in interactions
        ) or '<tr><td colspan="5">暂无交互记录</td></tr>'
        return (
            page
            .replace("{{UPLOAD_STATUS}}", upload_status)
            .replace("{{FILE_ROWS}}", file_rows)
            .replace("{{INTERACTION_ROWS}}", interaction_rows)
        )

    def download(self, fmt):
        if not self.state().get("teacher_logged_in"):
            return self.redirect("/teacher/login")
        rows = db_rows("SELECT * FROM interactions ORDER BY created_at ASC")
        if fmt == "json":
            body = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
            return self.bytes(body, "application/json", {"Content-Disposition": "attachment; filename=interactions.json"})
        output = StringIO()
        fieldnames = ["id", "session_id", "student_name", "agent", "user_message", "assistant_message", "phase", "metadata", "created_at"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return self.bytes(
            output.getvalue().encode("utf-8-sig"),
            "text/csv; charset=utf-8",
            {"Content-Disposition": "attachment; filename=interactions.csv"},
        )

    def static_file(self, name):
        path = (STATIC_DIR / name).resolve()
        if not str(path).startswith(str(STATIC_DIR.resolve())) or not path.exists():
            return self.not_found()
        mime = "text/css; charset=utf-8" if path.suffix == ".css" else "application/javascript; charset=utf-8"
        return self.bytes(path.read_bytes(), mime)

    def state(self):
        sid = None
        if "Cookie" in self.headers:
            jar = cookies.SimpleCookie(self.headers["Cookie"])
            if "sid" in jar:
                sid = jar["sid"].value
        if not sid or sid not in SESSIONS:
            sid = uuid4().hex
            SESSIONS[sid] = {}
            self.new_sid = sid
        return SESSIONS[sid]

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length)

    def read_json(self):
        try:
            return json.loads(self.read_body().decode("utf-8"))
        except Exception:
            return {}

    def redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.add_cookie()
        self.end_headers()

    def html(self, body, status=200):
        return self.bytes(body.encode("utf-8"), "text/html; charset=utf-8", status=status)

    def json(self, data, status=200):
        return self.bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status=status)

    def bytes(self, body, mime, extra_headers=None, status=200):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.add_cookie()
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def add_cookie(self):
        if hasattr(self, "new_sid"):
            self.send_header("Set-Cookie", f"sid={self.new_sid}; Path=/; SameSite=Lax")

    def not_found(self):
        return self.bytes("Not Found".encode("utf-8"), "text/plain; charset=utf-8", status=404)

    def log_message(self, fmt, *args):
        print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), fmt % args))
