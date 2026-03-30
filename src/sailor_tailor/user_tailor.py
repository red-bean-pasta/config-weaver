import logging

from sailor_tailor import exceptions as ex
from sailor_tailor import json_helper as helper, profile_patcher as patcher
from sailor_tailor.json_helper import JsonValue
from sailor_tailor.profile_modifier import ModifyPrerequisite
from sailor_tailor.profile_patcher import PatchPrerequisite

logger = logging.getLogger(__name__)


def apply_user_rules(
        username: str,
        user_rules: dict,
        material_profile: dict
) -> dict | None:
    """
    Modify directly on passed profile
    :param username:
    :param user_rules:
    :param material_profile:
    :return:
    """
    if material_profile is None or len(material_profile) == 0:
        return material_profile

    result = None
    for group_tag, group_specs in user_rules.items():
        logger.debug(f"Trying to apply rule group[{group_tag}]...")
        if not (normalized_specs := patcher.validate_rule_group_spec(group_tag, group_specs)):
            continue
        group_result = _apply_rule_group(username, normalized_specs, result if result is not None else material_profile)
        if group_result is not None:
            result = group_result
        else:
            logger.debug(f"No rule defined for '{username}' in group '{group_tag}'")

    if result is None:
        logger.debug(f"No rule group has match for '{username}'")
        return None
    return result


def _apply_rule_group(
        username: str,
        group_rules: list[dict],
        material_profile: dict
) -> dict | None:
    keys = {"$users", "$user"}
    patch_checker = PatchPrerequisite(
        keys,
        lambda r: _patch_user_check(username, r)
    )
    patch = patcher.extract_patches(group_rules, patch_checker)
    if patch is None:
        return None

    modify_checker = ModifyPrerequisite(
        keys,
        lambda r : _modify_user_check(username, r)
    )
    result = patcher.apply_patch(material_profile, patch, modify_checker)
    return result


def _patch_user_check(username: str, rule: dict[str, JsonValue]) -> bool:
    result = _extract_users(rule)
    if result is None: # no '$users' set
        raise ex.ConfigurationError("Top level '$users' must be set")
    users = result[1]
    return username in helper.to_list(users)


def _modify_user_check(username: str, rule: dict[str, JsonValue]) -> bool:
    result = _extract_users(rule)
    if result is None:  # no '$users' set
        return True
    users = result[1]
    return username in helper.to_list(users)


def _extract_users(rule: dict) -> tuple[str, list[JsonValue] | bool] | None:
    r = helper.get_with_aliases("$users", rule, "$user")
    if r is None:
        return None
    if not isinstance(r[1], list | str):
        raise ex.ConfigurationError(helper.get_invalid_type_log("$users", type(r[1])))
    return r[0], helper.as_list(r[1])
