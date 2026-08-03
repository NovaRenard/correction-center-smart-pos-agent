"""PyInstaller entry point for the windowed desktop executable."""

from smart_pos_agent.desktop.main import main

if __name__ == "__main__":
    raise SystemExit(main())
