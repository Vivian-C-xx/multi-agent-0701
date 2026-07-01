import os
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.server import Handler
from backend.storage import init_storage
from backend.utils import ensure_deepseek_api_key, load_env_file


def main():
    load_env_file()
    ensure_deepseek_api_key()
    init_storage()
    port = int(os.getenv("PORT", "5000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"http://127.0.0.1:{port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
