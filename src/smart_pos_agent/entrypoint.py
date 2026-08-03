"""PyInstaller entry point; imports the package rather than executing __main__.py as a file."""

from smart_pos_agent.cli import app

if __name__ == "__main__":
    app()
