class BaiduIndexError(Exception):
    """Raised when Baidu index data cannot be retrieved or parsed."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BaiduIndexRateLimitError(BaiduIndexError):
    """Raised when Baidu detects suspicious or high-frequency access."""

    def __init__(self, message: str) -> None:  # pragma: no cover - simple delegation
        super().__init__(message, status_code=429)
