

class XCRGReporter:
    """Interface for xCRG reporter that informs caller about events and progress."""

    def debug(self, message: str, *args: object) -> None:
        """Capture a debug message."""
        pass

    def info(self, message: str, *args: object) -> None:
        """Capture an info message."""
        pass

    def warning(self, message: str, *args: object) -> None:
        """Capture a warning message."""
        pass

    def error(self, message: str, *args: object) -> None:
        """Capture an error message."""
        pass

    def progress(self, pct_done: float):
        """Capture the current progress of the runner."""
        pass
