import copy
import logging
from dataclasses import dataclass
from typing import Self, Callable, Any

from sailor_tailor import (
    exceptions as ex,
    json_helper as helper,
    profile_selector as selector,
    profile_modifier as modifier,
    profile_placeholder_swapper as placeholder_swapper
)
from sailor_tailor.json_helper import JsonValue
from sailor_tailor.profile_modifier import ModifyPrerequisite

logger = logging.getLogger(__name__)


@dataclass
class Patch:
    selections: dict[str, JsonValue] | None # None means select everything while blank dict means select nothing
    modifications: list[dict] | None
    placeholders: dict[str, str] | None
    explanations: JsonValue

    def merge(self, addend: Self) -> Self:
        """
        Addend takes lower priority overridden
        :param addend:
        :return:
        """
        if self.selections is None or addend.selections is None:
            self.selections = None
        else:
            helper.override_merge_dict(addend.selections, self.selections)

        self.modifications = helper.merge_values_as_list(addend.modifications, self.modifications)

        helper.override_merge_dict(addend.placeholders, self.placeholders)


@dataclass
class PatchPrerequisite:
    custom_keys: set[str]
    evaluator: Callable[[dict[str, JsonValue]], bool]


def validate_rule_group_spec(tag: str, spec: Any) -> list[dict]:
    """
    :param tag:
    :param spec:
    :return:
    """
    normalized = helper.to_list(spec)
    if len(normalized) < 1:
        logger.debug(f"Encountered empty rule group: '{tag}'")
        return normalized
    if not isinstance(normalized[0], dict):
        raise ex.ConfigurationError(f"Unexpected body type: rule group '{tag}': {type(spec)}")
    return normalized


def extract_patches(
        rules: list[dict] | dict,
        prerequisite: PatchPrerequisite,
        count: int | None = None
) -> Patch | None:
    rules = helper.as_list(rules)
    if rules is None or len(rules) == 0:
        return None
    assert isinstance(rules[0], dict)

    patches : list[Patch] = []
    for rule in rules:
        patch = _extract_patch(rule, prerequisite)
        if patch is not None:
            patches.append(patch)
        if count is not None and len(patches) >= count:
            break

    if len(patches) < 1:
        return None
    merged = patches[-1]
    for p in patches[-2::-1]:
        merged.merge(p)
    return merged


def _extract_patch(rule: dict, prerequisite: PatchPrerequisite) -> Patch | None:
    assert isinstance(rule, dict)
    ks = _extract_selections(rule) # key + selection
    km = _extract_modifications(rule)
    kp = _extract_placeholders(rule)
    ke = _extract_explanations(rule)

    if not prerequisite.evaluator(rule):
        return None

    if ks is None and km is None and kp is None: # ke is not included: modifications can have explanations insides
        modifications = copy.copy(rule)
        for k in prerequisite.custom_keys:
            modifications.pop(k, None)
        return Patch(None, [modifications], None, None)

    unexpected = rule.keys() - prerequisite.custom_keys - {i[0] for i in [ks, km, kp, ke] if i is not None}
    if unexpected:
        raise ex.ConfigurationError(f"Unexpected keys: {unexpected}")

    return Patch(*[None if i is None else i[1] for i in [ks, km, kp, ke]])


def apply_patch(
        profile: dict,
        spec: Patch,
        custom_modify_checker: ModifyPrerequisite
) -> dict:
    """
    Modify directly on passed profile
    :param profile:
    :param spec:
    :param custom_modify_checker: Custom checker invoked in '$modifications' to see if a modification should apply
    :return:
    """
    if spec.selections is not None:
        logger.debug("Applying selections...")
        profile = selector.apply_selections(spec.selections, profile)
        logger.debug("Completed all selections")

    if spec.modifications is not None and len(spec.modifications) > 0:
        logger.debug("Applying modifications...")
        profile = modifier.apply_modifications(spec.modifications, custom_modify_checker, profile)
        logger.debug("Applied all modifications")

    if spec.placeholders is not None and len(spec.placeholders) > 0:
        for placeholder, value in spec.placeholders.items():
            logger.debug(f"Replacing placeholder '{placeholder}' to '{value}'...")
            profile = placeholder_swapper.recursive_replace_token(profile, placeholder, value, False)
        logger.debug("Replaced all placeholders")

    return profile


def _extract_selections(rule: dict) -> tuple[str, dict[str, JsonValue]] | None:
    r = helper.get_with_aliases(["$s", "$selections"], rule, "$selection")
    if r is None:
        return None
    if not isinstance(r[1], dict):
        raise ex.ConfigurationError(helper.get_invalid_type_log("$selections", type(r[1])))
    return r


def _extract_modifications(rule: dict) -> tuple[str, list[dict]] | None:
    r = helper.get_with_aliases(["$m", "$modifications"], rule, "$modification")
    if r is None:
        return None
    m = r[1]
    if isinstance(m, dict):
        m = helper.as_list(m)
    if not isinstance(m, list):
        raise ex.ConfigurationError(helper.get_invalid_type_log("$modifications", type(m)))
    if len(m) < 1:
        return None
    if not isinstance(m[0], dict):
        raise ex.ConfigurationError(helper.get_invalid_type_log("$modifications", f"list[{type(m[0])}]"))
    return r[0], m


def _extract_placeholders(rule: dict) -> tuple[str, dict[str, str]] | None:
    r = helper.get_with_aliases(["$h", "$placeholders"], rule, "$placeholder")
    if r is None:
        return None
    if not isinstance(r[1], dict):
        raise ex.ConfigurationError(helper.get_invalid_type_log("$placeholders", type(r[1])))
    return r


def _extract_explanations(rule: dict) -> tuple[str, JsonValue] | None:
    return helper.get_with_aliases(["$e", "$explanations"], rule, "$explanation")
