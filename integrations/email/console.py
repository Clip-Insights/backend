import logging

logger = logging.getLogger(__name__)


class ConsoleEmailSender:
    def send(self, to: str, subject: str, body: str) -> None:
        logger.info("EMAIL to=%s subject=%s\n%s", to, subject, body)
