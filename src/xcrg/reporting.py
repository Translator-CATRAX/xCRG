import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum

# The default logger for the LogReporter
_LOGGER = logging.getLogger(__name__)


class Message:
    """Marker class for messages reported by the xCRG module."""


class Log_Level(IntEnum):
    DEBUG    = logging.DEBUG
    INFO     = logging.INFO
    WARNING  = logging.WARNING
    ERROR    = logging.ERROR
    CRITICAL = logging.CRITICAL
    FATAL    = logging.FATAL


@dataclass
class Log_Message(Message):
    level : Log_Level
    msg   : str
    args  : tuple[object, ...] = field(default_factory = tuple)
    time  : datetime           = field(default = datetime.now(UTC))


# @dataclass
# class ProgressMessage(Message):
#     pct_done: float


class Reporter(ABC):
    """Abstract class for xCRG reporter that informs caller about events and progress."""
    @abstractmethod
    def handle_message(self, message: Message) -> None:
        """Handle a message from the xCRG module."""
        ...

    def debug(self, msg: str, *args: object):
        self.handle_message(Log_Message(Log_Level.DEBUG, msg, args))

    def info(self, msg: str, *args: object):
        self.handle_message(Log_Message(Log_Level.INFO, msg, args))

    def warning(self, msg: str, *args: object):
        self.handle_message(Log_Message(Log_Level.WARNING, msg, args))

    def error(self, msg: str, *args: object):
        self.handle_message(Log_Message(Log_Level.ERROR, msg, args))

    def critical(self, msg: str, *args: object):
        self.handle_message(Log_Message(Log_Level.CRITICAL, msg, args))

    def fatal(self, msg: str, *args: object):
        self.handle_message(Log_Message(Log_Level.FATAL, msg, args))


class Stub_Reporter(Reporter):
    """A reporter that does nothing with messages."""
    def handle_message(self, message: Message) -> None:
        pass


@dataclass
class Log_Reporter(Reporter):
    """A reporter that wraps the standard logging.Logger class."""
    logger: logging.Logger = field(default = _LOGGER)

    def handle_message(self, message: Message) -> None:
        match message:
            case Log_Message() as log:
                match log.level:
                    case Log_Level.DEBUG:    self.logger.debug(log.msg, *log.args)
                    case Log_Level.INFO:     self.logger.info(log.msg, *log.args)
                    case Log_Level.WARNING:  self.logger.warning(log.msg, *log.args)
                    case Log_Level.ERROR:    self.logger.error(log.msg, *log.args)
                    case Log_Level.CRITICAL: self.logger.critical(log.msg, *log.args)
                    case Log_Level.FATAL:    self.logger.fatal(log.msg, *log.args)
