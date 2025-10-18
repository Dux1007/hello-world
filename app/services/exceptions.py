class BaiduIndexError(Exception):
    """Raised when Baidu index data cannot be retrieved or parsed."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
