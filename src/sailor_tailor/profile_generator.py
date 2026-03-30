import copy
import json
import logging
import re

from sailor_tailor.config_manager import ConfigManager
from sailor_tailor.encryptor import decrypt_file
from sailor_tailor.user_tailor import apply_user_rules
from sailor_tailor.platform_tailor import apply_platform_rules
from sailor_tailor.version_tailor import apply_version_rules

logger = logging.getLogger(__name__)


def build_profile(
        config_manager: ConfigManager,
        key: str,
        user: str,
        user_agent: str | None,
        version: str | None
) -> dict:
    assert key is not None
    logger.info(f"Decrypting base profile for user '{user}'...")
    base = json.loads(decrypt_file(key, config_manager.get_encrypted_base()))
    clone = copy.deepcopy(base)

    assert user is not None
    user_rules = config_manager.get_user_rules()
    if user_rules:
        logger.info(f"Building profile for user '{user}'...")
        user_result = apply_user_rules(user, user_rules, clone)
    else:
        logger.debug("Skipped applying user rules: File not defined")
        user_result = clone

    if user_agent and (platform_rules := config_manager.get_platform_rules()):
        logger.info(f"Applying platform rules...")
        platform = _map_user_agent(user_agent, config_manager.get_agent_platform_map())
        platform_result = apply_platform_rules(platform, platform_rules, user_result)
    else:
        reason = "No user agent specified" if not user_agent else "File not defined"
        logger.debug(f"Skipped applying platform rules: {reason}")
        platform_result = user_result

    version_number = _normalize_version(version)
    if version_number and (version_rules := config_manager.get_version_rules()):
        logger.info(f"Applying version rules...")
        version_result = apply_version_rules(version_number, version_rules, platform_result)
    else:
        reason = "No version specified" if not version else "File not defined"
        logger.debug(f"Skipped applying version rules: {reason}")
        version_result = platform_result

    return version_result


def _map_user_agent(agent: str, agent_platform_map: dict | None) -> str:
    user_agent = _normalize_user_agent(agent)
    if not agent_platform_map:
        logger.debug(f"Skipped mapping user agent '{user_agent}': Map not defined")
        return user_agent
    platform = agent_platform_map.get(user_agent)
    if platform:
        logger.debug(f"Mapped user agent '{user_agent}' to platform '{platform}'")
        return platform
    else:
        logger.debug(f"User agent '{user_agent}' not mapped. Using it as is...")
        return user_agent


def _normalize_version(version: str | None) -> str | None:
    """
    1.0.0-alpha => 1.0.0
    :param version:
    :return:
    """
    if version is None:
        return None
    return re.search(r'([\d.]+)*', version)


def _normalize_user_agent(agent: str) -> str:
    return agent.strip().partition('/')[0]