import logging
from enum import StrEnum
from pathlib import Path

from sailor_tailor.config_manager import ConfigManager


logger = logging.getLogger(__name__)


class StaticConfigFilename(StrEnum):
    AUTH = "auth_rules.json"
    BASE = "base.enc"
    USER = "user_rules.json"
    PLATFORM = "platform_rules.json"
    VERSION = "version_rules.json"

class StateConfigFilename(StrEnum):
    REVOKED = "revoked_auth_rules.json"

class FileImportance(StrEnum):
    """
    SKIPPED -> Doesn't use this file;
    MISSABLE -> Will be used, and missing is normal and expected with handling logic, e.g., creation;
    OPTIONAL -> Will be used if found, else not used and logged
    """
    SKIPPED = "skipped"
    MISSABLE = "missable"
    OPTIONAL = "optional"
    RECOMMENDED = "recommended"
    REQUIRED = "required"

importance_log_level_dict : dict[FileImportance, int] = {
    FileImportance.OPTIONAL : 10,
    FileImportance.RECOMMENDED : 30,
    FileImportance.REQUIRED : 50
}


def construct_config_manager(
        config_dir: str | None,
        state_dir: str | None,
        importance_overrides: dict[str, FileImportance] | None = None
) -> ConfigManager:
    if importance_overrides is None: importance_overrides = {}
    return ConfigManager(
        _get_config_path_helper(config_dir, StaticConfigFilename.AUTH, FileImportance.REQUIRED, importance_overrides),
        _get_config_path_helper(config_dir, StaticConfigFilename.BASE, FileImportance.REQUIRED, importance_overrides),
        _get_config_path_helper(config_dir, StaticConfigFilename.USER, FileImportance.RECOMMENDED, importance_overrides),
        _get_config_path_helper(config_dir, StaticConfigFilename.PLATFORM, FileImportance.RECOMMENDED, importance_overrides),
        _get_config_path_helper(config_dir, StaticConfigFilename.VERSION, FileImportance.RECOMMENDED, importance_overrides),
        _get_config_path_helper(state_dir, StateConfigFilename.REVOKED, FileImportance.MISSABLE, importance_overrides)
    )


def _get_config_path_helper(
        parent_dir: str | Path | None,
        filename: str,
        importance: FileImportance,
        overrides: dict[str, FileImportance]
) -> Path | None:
    return _get_config_path(
        parent_dir,
        filename,
        overrides.get(filename) or importance
    )


def _get_config_path(parent_dir: str | Path | None, filename: str, importance: FileImportance) -> Path | None:
    if importance == FileImportance.SKIPPED:
        return None

    if parent_dir is None:
        message = f"{importance} file {filename} not defined: Directory not defined"
    else:
        path = Path(parent_dir) / filename
        if importance == FileImportance.MISSABLE:
            return path
        if not path.exists():
            message = f"{importance} {path} not defined: File not found"
        else:
            message = None

    if message is not None:
        if importance == FileImportance.REQUIRED:
            raise FileNotFoundError(message)
        logger.log(importance_log_level_dict[importance], message)
        return None
    else:
        logger.debug(f"Found {path}")
        return path