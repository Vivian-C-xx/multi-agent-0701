import os
from pathlib import Path
from uuid import uuid4

from backend.config import BASE_DIR, DATA_DIR, UPLOAD_DIR


def upload_dir_candidates():
    configured = os.getenv("APP_UPLOAD_DIR", "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend([UPLOAD_DIR, DATA_DIR / "uploads", BASE_DIR / "uploaded_knowledge"])

    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate.absolute()
        if resolved in seen:
            continue
        seen.add(resolved)
        yield resolved


def ensure_writable_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    probe = path / f".write_probe_{uuid4().hex}.tmp"
    try:
        probe.write_bytes(b"ok")
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
    return path


def choose_upload_dir():
    errors = []
    for candidate in upload_dir_candidates():
        try:
            return ensure_writable_dir(candidate)
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")
    raise OSError("; ".join(errors) or "no writable upload directory")


def find_upload_file(saved_name):
    for directory in upload_dir_candidates():
        path = directory / saved_name
        if path.exists() and path.is_file():
            return path
    return None


def iter_upload_files():
    seen = set()
    for directory in upload_dir_candidates():
        try:
            paths = list(directory.iterdir())
        except OSError:
            continue
        for path in paths:
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path.absolute()
            if resolved in seen or not path.is_file():
                continue
            seen.add(resolved)
            yield path
