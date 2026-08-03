from __future__ import annotations


class SmartPosError(Exception):
    """Base error for an official Smart POS request."""


class SmartPosTransportError(SmartPosError):
    pass


class SmartPosHttpError(SmartPosError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class SmartPosApiError(SmartPosError):
    def __init__(self, status_code: int, error_text: str | None = None) -> None:
        super().__init__(error_text or f"Smart POS error {status_code}")
        self.status_code = status_code
        self.error_text = error_text


class AuthenticationError(SmartPosApiError):
    pass


class TerminalBusyError(SmartPosApiError):
    pass


class ValidationApiError(SmartPosApiError):
    pass
