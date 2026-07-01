import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from backend.config import BASE_DIR, DATA_DIR, UPLOAD_DIR
from backend.upload_store import choose_upload_dir

DB_PATH = DATA_DIR / "app.db"

def init_storage():
    global DB_PATH
    DATA_DIR.mkdir(exist_ok=True)
    try:
        active_upload_dir = choose_upload_dir()
        if active_upload_dir != UPLOAD_DIR.resolve():
            print(f"[WARN] uploads 目录不可写，教师上传资料将保存到：{active_upload_dir}")
    except OSError as exc:
        print(f"[WARN] 暂未找到可写上传目录，教师端上传时会提示错误：{exc}")
    DB_PATH = choose_db_path()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                student_name TEXT,
                agent TEXT NOT NULL,
                user_message TEXT NOT NULL,
                assistant_message TEXT NOT NULL,
                phase TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_name TEXT NOT NULL,
                saved_name TEXT NOT NULL,
                file_type TEXT NOT NULL,
                knowledge_summary TEXT,
                uploaded_at TEXT NOT NULL
            )
            """
        )
        ensure_column(conn, "knowledge_files", "knowledge_summary", "TEXT")

def ensure_column(conn, table, column, column_type):
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

def choose_db_path():
    configured = os.getenv("APP_DB_PATH", "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend([DATA_DIR / "app.db", BASE_DIR / "app.db"])
    seen = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            probe = candidate.parent / f".write_probe_{uuid4().hex}.tmp"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            with sqlite3.connect(candidate) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.rollback()
            if candidate != DATA_DIR / "app.db":
                print(f"[WARN] data 目录不可写，数据库已切换到：{candidate}")
            return candidate
        except (OSError, sqlite3.Error) as exc:
            print(f"[WARN] 数据库目录不可写，跳过 {candidate}：{exc}")
    raise RuntimeError("没有可写的数据库目录，请检查项目目录权限。")

def db_rows(query, args=()):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, args).fetchall()]

def execute(query, args=()):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(query, args)

def recent_knowledge_names():
    rows = db_rows("SELECT original_name FROM knowledge_files ORDER BY uploaded_at DESC LIMIT 6")
    return "、".join(row["original_name"] for row in rows) or "暂无教师上传资料"

def save_interaction(state, agent, user_message, assistant_message, phase="", metadata=None):
    try:
        execute(
            """
            INSERT INTO interactions
            (session_id, student_name, agent, user_message, assistant_message, phase, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state.setdefault("student_session_id", str(uuid4())),
                state.get("student_name", ""),
                agent,
                user_message,
                assistant_message,
                phase,
                json.dumps(metadata or {}, ensure_ascii=False),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        return True
    except Exception as exc:
        print(f"[WARN] 交互记录保存失败，但聊天响应已继续返回：{exc}")
        return False
