"""
Entry point. Run with:  python app.py
Then open:              http://localhost:8000
"""
import webbrowser
import threading

import uvicorn

from backend import config


def _open_browser():
    webbrowser.open(f"http://localhost:{config.PORT}")


if __name__ == "__main__":
    threading.Timer(1.5, _open_browser).start()
    uvicorn.run("backend.main:app", host=config.HOST, port=config.PORT, reload=False)
