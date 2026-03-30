import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Iterable

from sailor_tailor import json_helper as helper
from sailor_tailor.json_helper import JsonValue, FieldValue
from sailor_tailor import exceptions as ex


logger = logging.getLogger(__name__)


class Action(StrEnum):
    ADD = "+"
    ASSIGN = "="
    REMOVE = "-"
    RENAME = ">"


@dataclass
class Operation:
    action: Action
    index: int | None
    elements: str | list | dict

@dataclass
class ModifyPrerequisite:
    custom_keys : set[str]
    evaluator: Callable[[dict[str, JsonValue]], bool]


def apply_modifications(
        rules: dict | list[dict],
        checker: ModifyPrerequisite | None,
        material_profile: dict[str, JsonValue]
) -> dict:
    """
    Modify directly on passed `parent_config`. Make deep copy first before passing if needed.
    :param rules:
    :param checker:
    :param material_profile:
    :return:
    """
    target = material_profile

    if rules is None:
        return material_profile
    if isinstance(rules, dict):
        rules = helper.as_list(rules)
    if not isinstance(rules, list):
        raise ex.ConfigurationError(f"Unexpected '$modifications' format: {type(rules)}")
    if len(rules) < 1:
        return material_profile
    if not isinstance(rules[0], dict):
        raise ex.ConfigurationError(f"Unexpected '$modifications' rule format: {type(rules[0])}")

    for i, rule in enumerate(rules):
        logger.debug(f"Trying to apply rule[{i}]...")
        target = _apply_rule(rule, checker, target)
    return target


def _apply_rule(
        rule: dict,
        checker: ModifyPrerequisite,
        target: JsonValue
) -> JsonValue:
    ke = _extract_explanations(rule)
    kc = _extract_conditions(rule)
    ka = _extract_actions(rule)

    unspecified = helper.get_unspecified_key_value_pairs(rule, ke, kc, *(ka or ())).keys()
    unspecified -= checker.custom_keys
    def _custom_check(mp: ModifyPrerequisite | None) -> bool:
        if mp is None or mp.evaluator(rule):
            return True
        logger.debug("Custom check failed. Skipping...")
        return False
    if unspecified:
        if ka is not None:
            raise ex.ConfigurationError(f"Unexpected keys when '$actions' is set: {unspecified}")
        if kc is not None and not _check_conditions(kc[1], target):
            logger.debug("Condition not satisfied. Skipping...")
            return target
        if not _custom_check(checker):
            return target
        for field in unspecified:
            logger.debug(f"Trying to modify '{field}'...")
            target[field] = apply_modifications(rule[field], checker, target[field])
            logger.debug(f"Finished modifying '{field}'")
        return target
    else:
        if ka is None:
            raise ex.ConfigurationError(f"Unable to locate '$actions'")
        if not _custom_check(checker):
            return target
        return _apply_operations([a[1] for a in ka], kc, target)


def _apply_operations(
        operations: Iterable[Operation],
        conditions: list[dict] | None,
        target: JsonValue
) -> JsonValue | None:
    for o in operations:
        target = _apply_operation(o, conditions, target)


def _apply_operation(
        operation: Operation,
        conditions: list[dict] | None,
        target: JsonValue
) -> JsonValue | None:
    action = operation.action
    index = operation.index
    elements = operation.elements
    if isinstance(target, list):
        if action == Action.ADD:
            logger.debug(f"Applying add rule on array target...")
            return _add(elements, conditions, index, target)
        else:
            logger.debug(f"Applying non-add rule on array target...")
            for i, target_element in enumerate(target):
                logger.debug(f"Applying on target element[{i}]...")
                _apply_operation(operation, conditions, target_element)
            return target
    elif isinstance(target, dict):
        if action == Action.ADD:
            target = helper.as_list(target)
            return _apply_operation(operation, conditions, target)
        else:
            if conditions is not None and not _check_conditions(conditions, target):
                logger.debug(f"Condition not satisfied. Skipping...")
            elif action == Action.ASSIGN:
                logger.debug(f"Applying {action}...")
                _assign(elements, target)
            elif action == Action.REMOVE:
                logger.debug(f"Applying {action}...")
                _remove(elements, target)
            else:
                raise AssertionError(f"Unexpected action: {action.name}. It should be handled upstream")
            return target
    elif target is not None and action == Action.ADD:
        target = helper.as_list(target)
        return _apply_operation(operation, conditions, target)
    else:
        raise ex.ConfigurationError(f"Invalid operation: Trying to apply {action} to {type(target)} type field")


def _add(items: FieldValue, conditions:list[dict], index: int | None, profile: list) -> list:
    if len(items) <= 0:
        return profile

    if type(items[0]) != type(profile[0]):
        raise AssertionError(f"Trying to insert {type(items[0])} value into {type(profile[0])} config")

    length = len(profile)
    if conditions is not None:
        logger.debug("`$conditions` set. Finding the first matched candidate...")
        if index is None:
            index = 0
        matched = length
        for i, element in enumerate(profile):
            if _check_conditions(conditions, element):
                matched = i
                break
            continue
        index = _clamp(0, length, matched + index)

    if index is None:
        index = len(profile)

    profile[index:index] = items
    return profile


def _assign(items: dict, profile: dict[str, JsonValue]) -> JsonValue:
    if not isinstance(items, dict):
        raise ex.ConfigurationError(f"Invalid '$items': Invalid type: {type(items)}")

    for field, value in items.items():
        if not isinstance(value, dict):
            profile[field] = value
            continue
        if field not in profile:
            profile[field] = value
            continue
        sub_profile = profile[field]
        if not isinstance(sub_profile, dict):
            raise ex.ConfigurationError(f"Invalid operation: Trying to assign object to non-object field: '{field}': '{sub_profile}' => '{field}': '{value}'")
        _assign(field, profile[field])


def _remove(items: str | list | dict, profile: dict[str, JsonValue]):
    if isinstance(items, str | list):
        items = helper.as_list(items)
        for item in items:
            if item in profile:
                profile.pop(item)
            else:
                logger.debug(f"Skipped removing '{item}': Key not found")
    else:
        for scope, sub_items in items.items():
            if scope not in profile:
                logger.debug(f"Skipped removing '{scope}': Key not found")
                continue
            if isinstance(profile[scope], dict):
                raise ex.ConfigurationError(f"Invalid operation: Trying to remove from non-object: Removing '{sub_items}' from '{scope}': '{profile[scope]}'")
            _remove(sub_items, profile[scope])


def _check_conditions(or_conditions: list[dict[str, JsonValue]], config: dict[str, JsonValue]) -> bool:
    for c in or_conditions:
        if _check_condition_combination(c, config):
            return True
    return False


def _check_condition_combination(and_conditions: dict[str, JsonValue], config: dict[str, JsonValue]) -> bool:
    for field, value in and_conditions.items():
        if field not in config:
            if value is None: continue
            else: return False
        if isinstance(value, dict):
            return _check_condition_combination(value, config[field])
        elif isinstance(value, list):
            raise ex.ConfigurationError("Invalid operation: Comparing array is currently not supported")
        else:
            if config[field] == value: continue
            else: return False
    return True


def _extract_conditions(rule: dict[str, JsonValue]) -> tuple[str, list[dict[str, JsonValue]]] | None:
    r = helper.get_with_aliases(["$c", "$conditions"], rule, "$condition")
    if r is None:
        return None
    if isinstance(r[1], dict):
        return r[0], helper.as_list(r[1])
    if isinstance(r[1], list):
        return r
    raise ex.ConfigurationError(f"Invalid '$conditions': Invalid type: {type(r)}")


def _extract_actions(rule: dict[str, JsonValue]) -> list[tuple[str, Operation]] | None:
    result : list[tuple[str, Operation]] = []
    for a in Action:
        key = "$" + a
        if key not in rule:
            continue

        if not isinstance(rule[key], dict):
            result.append((key, Operation(a, None, rule[key])))
            continue

        ki = _extract_index(rule)
        ke = _extract_elements(rule)
        if ki is None and ke is None:
            result.append((key, Operation(a, None, rule[key])))
            continue
        if ki is not None and ke is None:
            raise ex.ConfigurationError(f"No '$elements' specified: {rule[key]}")
        if len(unspecified := helper.get_unspecified_key_value_pairs(rule, ki, ke)) > 0:
            raise ex.ConfigurationError(f"Unexpected keys: {unspecified.keys()}")
        result.append((key, Operation(a, ki[1], ke[1])))
    return result if len(result) > 0 else None


def _extract_index(rule: dict[str, JsonValue]) -> tuple[str, int] | None:
    r = helper.get_with_aliases(["$i", "$index"], rule, ["$indexes", "$indices"])
    if r is None: return None
    assert isinstance(r[1], int | None), helper.get_invalid_type_log("$index", type(r[1]))
    return r


def _extract_elements(rule: dict[str, JsonValue]) -> tuple[str, FieldValue] | None:
    r = helper.get_with_aliases(["$e", "$elements"], rule, "element")
    if r is None:
        return None
    assert isinstance(r[1], FieldValue | None), helper.get_invalid_type_log("$elements", type(r[1]))
    return r


def _extract_explanations(rule: dict) -> tuple[str, FieldValue] | None:
    return helper.get_with_aliases(["$e", "$explanations"], rule, "$explanation")


def _clamp(min_v: int, max_v: int, v: int) -> int:
    return max(min_v, min(v, max_v))