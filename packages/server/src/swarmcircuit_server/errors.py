"""Public errors contain useful classifications, never raw payloads or SQL."""


class Problem(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


class InvalidRecord(ValueError):
    """A permanently invalid or conflicting individual ingestion record."""
