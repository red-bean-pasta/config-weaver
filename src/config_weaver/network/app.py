import logging
import os

from fastapi import FastAPI

from config_weaver import manager_helper
from config_weaver.meta import APP_ABBR
from config_weaver.network import request_handler
from config_weaver.network.http_revoker import HttpAuthRevokeMiddleware
from config_weaver.utils import logging_helper

SPEC_DIR_ENV = f"_{APP_ABBR}_SPEC_DIR"
STATE_DIR_ENV = f"_{APP_ABBR}_STATE_DIR"
UNSAFE_MODE_ENV = f"_{APP_ABBR}_UNSAFE_MODE"
LOG_LEVEL_ENV = f"_{APP_ABBR}_LOG_LEVEL"


def create() -> FastAPI:
    _initialize_logging()

    app = FastAPI()
    app.include_router(request_handler.router)
    app.add_middleware(HttpAuthRevokeMiddleware)

    spec_dir = os.environ[SPEC_DIR_ENV]
    state_dir = os.environ[STATE_DIR_ENV]
    app.state.config_manager = manager_helper.build_config_manager(spec_dir)
    app.state.auth_manager = manager_helper.build_auth_manager(spec_dir, state_dir)
    app.state.patch_manager = manager_helper.build_patch_manager(spec_dir)
    app.state.unsafe_mode = True if int(os.environ[UNSAFE_MODE_ENV]) else False

    return app


def _initialize_logging():
    logging_helper.initialize(os.environ[LOG_LEVEL_ENV])
    _add_logger_filter()


def _add_logger_filter():
    logger = logging.getLogger("uvicorn.access")
    for h in logger.handlers:
        h.addFilter(_strip_path)


def _strip_path(record: logging.LogRecord):
    if len(record.args) >= 3:
        record.args = record.args[:2] + ("REDACTED",) + record.args[3:]
    return True