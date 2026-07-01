import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from backend.storage import db_rows
from backend.upload_store import find_upload_file

MAX_TEXT_CHARS = 4000
MAX_CONTEXT_CHARS = 1800


def extract_text(path):
    suffix = Path(path).suffix.lower()
    if suffix in {".txt", ".md"}:
        return Path(path).read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pptx":
        return extract_pptx_text(path)
    if suffix == ".docx":
        return extract_docx_text(path)
    return ""


def extract_pptx_text(path):
    texts = []
    with zipfile.ZipFile(path) as archive:
        slide_names = sorted(
            name for name in archive.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )
        for name in slide_names:
            texts.extend(extract_xml_text(archive.read(name)))
    return "\n".join(texts)


def extract_docx_text(path):
    with zipfile.ZipFile(path) as archive:
        if "word/document.xml" not in archive.namelist():
            return ""
        return "\n".join(extract_xml_text(archive.read("word/document.xml")))


def extract_xml_text(raw):
    root = ElementTree.fromstring(raw)
    texts = []
    for element in root.iter():
        if element.tag.endswith("}t") and element.text:
            text = normalize_text(element.text)
            if text:
                texts.append(text)
    return texts


def normalize_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def build_knowledge_summary(text):
    normalized = normalize_text(text)
    if not normalized:
        return "暂未提取到可读文本，请根据文件名和学生题干判断知识点。"
    return normalized[:MAX_TEXT_CHARS]


def recent_knowledge_context():
    rows = db_rows(
        """
        SELECT original_name, file_type, knowledge_summary
        FROM knowledge_files
        ORDER BY uploaded_at DESC
        LIMIT 3
        """
    )
    parts = []
    for row in rows:
        saved_summary = normalize_text(row.get("knowledge_summary", ""))
        if not saved_summary:
            saved_summary = "暂未提取到可读文本。"
        parts.append(
            f"文件《{row['original_name']}》（{row['file_type']}）涉及内容：{saved_summary[:MAX_CONTEXT_CHARS]}"
        )
    return "\n".join(parts) or "暂无教师上传资料。"


def existing_upload_rows():
    rows = db_rows("SELECT * FROM knowledge_files ORDER BY uploaded_at DESC")
    return [row for row in rows if find_upload_file(row["saved_name"])]
