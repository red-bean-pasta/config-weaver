import logging
import sys

logger = logging.getLogger(__name__)

MODULE_NAME = __package__.split('.')[0]
APP_NAME = MODULE_NAME.replace("_", "-")
APP_ABBR = ''.join(part[0] for part in APP_NAME.split('-')).upper()

PRESERVED_PREFIX = "$"


def initialize_logging(level: str):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(levelname)s: %(name)s: %(message)s",
    )
    global logger; logger = logging.getLogger(__name__)


def exit_on_error(message: str | Exception, status_code: int = 1):
    logger.fatal("ERROR: " + str(message))
    sys.exit(status_code)
