"""Do not record search terms or legacy WebSocket tokens in request paths."""

import logging


class RequestPathFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                arg.partition("?")[0]
                if isinstance(arg, str) and arg.startswith("/api/")
                else arg
                for arg in record.args
            )
        return True
