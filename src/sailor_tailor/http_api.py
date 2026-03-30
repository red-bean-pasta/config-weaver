import logging
import os

from fastapi import FastAPI

from sailor_tailor.app_helper import APP_ABBR, exit_on_error, initialize_logging
from sailor_tailor.config_manager_factory import construct_config_manager
from sailor_tailor.http_request_handler import router, HttpAuthRevokeMiddleware


CONFIG_DIR_ENV = f"_{APP_ABBR}_CONFIG_DIR"
STATE_DIR_ENV = f"_{APP_ABBR}_STATE_DIR"
UNSAFE_MODE_ENV = f"_{APP_ABBR}_UNSAFE_MODE"
LOG_LEVEL_ENV = f"_{APP_ABBR}_LOG_LEVEL"


def create_http_api() -> FastAPI:
    initialize_logging(os.environ[LOG_LEVEL_ENV])

    api = FastAPI()
    api.include_router(router)
    api.add_middleware(HttpAuthRevokeMiddleware)

    add_logger_filter()

    config_dir = os.environ[CONFIG_DIR_ENV]
    state_dir = os.environ[STATE_DIR_ENV]
    try:
        manager = construct_config_manager(config_dir, state_dir)
    except Exception as e:
        exit_on_error(e)
    api.state.config_manager = manager

    api.state.unsafe_mode = True if int(os.environ[UNSAFE_MODE_ENV]) else False

    return api


def add_logger_filter():
    logger = logging.getLogger("uvicorn.access")
    for h in logger.handlers:
        h.addFilter(_path_stripper)


def _path_stripper(record):
    if len(record.args) >= 3:
        record.args = record.args[:2] + ("REDACTED",) + record.args[3:]
    return True