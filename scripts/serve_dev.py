"""Dev server launcher for the redesign mission (avoids shell quote-stripping).

Runs the Flask app on 127.0.0.1:5199 without the debug reloader so template
edits require a restart (by design during the redesign). Usage:

    .venv\\Scripts\\python.exe scripts\\serve_dev.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5199, debug=False, use_reloader=False)
