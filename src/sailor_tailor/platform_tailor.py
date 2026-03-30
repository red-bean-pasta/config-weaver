import logging
from typing import Union

from sailor_tailor import json_helper as helper, profile_patcher as patcher
from sailor_tailor.json_helper import JsonValue
from sailor_tailor import exceptions as ex
from sailor_tailor.profile_modifier import ModifyPrerequisite
from sailor_tailor.profile_patcher import PatchPrerequisite

FieldValue = Union[str, list[str], dict[str, JsonValue]]

logger = logging.getLogger(__name__)


def apply_platform_rules(
        client_platform: str,
        platform_rules: dict[str, dict | list],
        material_profile: dict[str, JsonValue]
) -> dict | None:
    if material_profile is None or len(material_profile) == 0:
        return material_profile

    for group_tag, group_specs in platform_rules.items():
        logger.debug(f"Processing group[{group_tag}]...")
        if not (normalized_specs := patcher.validate_rule_group_spec(group_tag, group_specs)):
            continue
        material_profile = _apply_rule_group(client_platform, normalized_specs, material_profile)
        logger.debug(f"Finished applying rule group[{group_tag}]")

    logger.debug("Finished applying every rule group")
    return material_profile


def _apply_rule_group(
        client_platform: str,
        group_rules: list[dict],
        material_profile: dict
) -> dict | None:
    assert isinstance(group_rules, list)

    keys = {"platforms", "$platform"}
    args = [keys, lambda r: _platform_check(client_platform, r)]
    patch_checker = PatchPrerequisite(*args)
    modify_checker = ModifyPrerequisite(*args)

    patches = patcher.extract_patches(group_rules, patch_checker)
    if patches is None:
        return material_profile
    return patcher.apply_patch(material_profile, patches, modify_checker)


def _platform_check(client_platform: str, rule: dict[str, JsonValue]) -> bool:
    kp = _extract_platforms(rule)
    if kp is None:
        return True
    platforms = kp[1]
    return client_platform in helper.to_list(platforms)


def _extract_platforms(rule: dict[str, JsonValue]) -> tuple[str, list[str]] | None:
    r = helper.get_with_aliases("$platforms", rule, "$platform")
    if r is None:
        return None
    if isinstance(r[1], str):
        return r[0], helper.as_list(r[1])
    if isinstance(r[1], list):
        return r
    raise ex.ConfigurationError(f"Invalid type: `$platform`: {type(r[1])}")