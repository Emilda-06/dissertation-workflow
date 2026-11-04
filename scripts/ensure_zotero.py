"""Make sure Zotero (with Better BibTeX) is open; start it if it isn't.

Runs automatically when a Claude Code session starts (SessionStart hook in .claude/settings.json)
and at the start of every reference, research, import and build script.

Usage:  python scripts/ensure_zotero.py      (skipped when the active project sets zotero.enabled: false)
"""
from common import ensure_zotero, init_cli, load_config, zotero_ready


def main():
    init_cli()
    cfg = load_config(require_project=False)
    if (cfg.get("zotero") or {}).get("enabled", True) is False:
        print("Zotero: disabled for this project")
        return
    was_running = zotero_ready(cfg)
    ensure_zotero(cfg)
    print("Zotero: running" if was_running else "Zotero: started automatically and ready")


if __name__ == "__main__":
    main()
