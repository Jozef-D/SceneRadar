import logging
import sys


def configure_logging(service_name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format=f"[{service_name}] %(asctime)s %(levelname)s: %(message)s",
        stream=sys.stdout,
    )
    return logging.getLogger(service_name)
