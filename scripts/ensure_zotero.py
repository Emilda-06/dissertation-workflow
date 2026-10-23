"""Make sure Zotero (with Better BibTeX) is open; start it if it isn't.

Runs automatically when a Claude Code session starts (SessionStart hook in .claude/settings.json)
and at the start of every reference, research, import and build script.

Usage:  .venv/Scripts/python.exe scripts/ensure_zotero.py
"""
from common import ensure_zotero, load_config, setup_stdout, zotero_ready


def main():
    setup_stdout()
    cfg = load_config()
    was_running = zotero_ready(cfg)
    ensure_zotero(cfg)
    print("Zotero: running" if was_running else "Zotero: started automatically and ready")


if __name__ == "__main__":
    main()
