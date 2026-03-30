import logging

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from sailor_tailor import exceptions as ex
from sailor_tailor import json_helper as helper, profile_patcher as patcher
from sailor_tailor.json_helper import JsonValue
from sailor_tailor.profile_modifier import ModifyPrerequisite
from sailor_tailor.profile_patcher import PatchPrerequisite


logger = logging.getLogger(__name__)


def apply_version_rules(
        client_version: str,
        version_rules: dict,
        material_profile: dict
) -> dict | None:
    """
    Modify directly on passed profile
    :param client_version:
    :param version_rules:
    :param material_profile:
    :return:
    """
    if material_profile is None or len(material_profile) == 0:
        return material_profile

    for group_tag, group_specs in version_rules.items():
        logger.debug(f"Applying rule group[{group_tag}]...")
        if not (normalized_specs := patcher.validate_rule_group_spec(group_tag, group_specs)):
            continue
        material_profile = _apply_rule_group(client_version, normalized_specs, material_profile)
        logger.debug(f"Finished applying rule group[{group_tag}]")

    logger.debug("Finished applying every rule group")
    return material_profile


def _apply_rule_group(
        client_version: str,
        group_rules: list[dict],
        material_profile: dict
) -> dict | None:
    keys = {"$version", "$versions"}
    args = [keys, lambda r: _version_check(client_version, r)]
    patch_checker = PatchPrerequisite(*args)
    modify_checker = ModifyPrerequisite(*args)

    patches = patcher.extract_patches(group_rules, patch_checker)
    if patches is None:
        return material_profile
    return patcher.apply_patch(material_profile, patches, modify_checker)


def _version_check(client_version: str, rule: dict[str, JsonValue]) -> bool:
    result = _extract_version(rule)
    if result is None:
        return True
    spec = result[1]
    return _check_version(client_version, spec)


def _check_version(client_version: str, applicable_version_spec: str):
    v = Version(client_version)
    s = SpecifierSet(applicable_version_spec)
    return v in s


def _extract_version(rule: dict) -> tuple[str, str] | None:
    r = helper.get_with_aliases("$version", rule, "$versions")
    if r is None:
        return None
    if not isinstance(r[1], str):
        raise ex.ConfigurationError(helper.get_invalid_type_log("$version", type(r[1])))
    return r