import logging
import traceback
import sys

class TracebackFormatter(logging.Formatter):
    def format(self, record):
        log_msg = super().format(record)

        # Auto include traceback if error
        exc = record.exc_info
        if not exc and record.levelno >= logging.ERROR:
            exc = sys.exc_info()

        if exc and exc[0] is not None:
            log_msg += "\n" + "".join(traceback.format_exception(*exc))

        return log_msg