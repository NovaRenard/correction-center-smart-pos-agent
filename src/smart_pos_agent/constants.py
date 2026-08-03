from pathlib import Path

AGENT_PROTOCOL_VERSION = 1
KEYRING_SERVICE = "KoshakanSmartPosAgent"
DEFAULT_WINDOWS_DATA_DIRECTORY = Path("C:/ProgramData/KoshakanSmartPosAgent")
TOKEN_REFRESH_SKEW_SECONDS = 300
FINAL_STATUSES = frozenset({"success", "fail"})
ACTIVE_STATUSES = frozenset({"accepted", "started", "wait", "unknown"})
