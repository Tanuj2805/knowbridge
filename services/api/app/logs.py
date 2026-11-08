import logging

from app.config import get_settings


def configure() -> None:
    logging.basicConfig(
        level=get_settings().log_level,
        format='{"t":"%(asctime)s","lvl":"%(levelname)s","log":"%(name)s","msg":"%(message)s"}',
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
