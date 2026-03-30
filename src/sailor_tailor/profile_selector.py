import copy
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from sailor_tailor import json_helper as helper, exceptions as ex
from sailor_tailor.json_helper import JsonValue


logger = logging.getLogger(__name__)

KeyValue = str | int | float | bool

class MergeLogic(StrEnum):
    UNION = "union"
    DIFFERENCE = "difference"
    INTERSECTION = "intersection"

@dataclass
class Entity:
    target_key: str
    override_specs: dict[str, dict]

# Though not implemented yet
class Selections:
    layers: list[Entity]
    merge_logic: MergeLogic
    pivot_key: str


def apply_selections(
        rules: dict[str, dict | list] | None,
        material_profile: dict[str, JsonValue]
) -> dict:
    """
    Modify directly on passed profile. Make a deep copy first before passing if needed
    :param material_profile:
    :param rules:
    :return:
    """
    if rules is None:
        return material_profile

    for target, body in rules.items():
        if isinstance(body, list):
            material_profile[target] = _apply_rules(target, body, material_profile)
        elif isinstance(body, dict):
            if _check_operation_present(body): # operator is the identifier
                material_profile[target] = _apply_rules(target, [body], material_profile)
            else:
                material_profile[target] = apply_selections(body, material_profile[target])
        else:
            raise ex.ConfigurationError(f"Invalid selection body for '{target}': {str(body)}")

    return material_profile


def _apply_rules(
        target_key: str,
        target_rules: list[dict],
        material_profile: dict[str, JsonValue]
) -> list:
    logger.debug(f"Selecting from {target_key}...")

    if isinstance(target_rules, dict):
        target_rules = helper.as_list(target_rules)
    if not isinstance(target_rules, list):
        raise ex.ConfigurationError(f"Invalid body type: {type(target_rules)}")
    if not isinstance(target_rules[0], dict):
        raise ex.ConfigurationError(f"Invalid selection rule type: {type(target_rules)}")

    if target_key not in material_profile:
        raise ex.ConfigurationError(f"`{target_key}` not found in passed profile")
    target_body = material_profile[target_key]
    if isinstance(target_body, dict):
        target_body = helper.as_list(target_rules)
    if not isinstance(target_body, list):
        raise ex.ConfigurationError(f"Trying to select from invalid type: {type(target_body)}")

    current_body = None
    for i, rule in enumerate(target_rules):
        logger.debug(f"Applying selection[{i}]...")
        current_body = _apply_rule(rule, current_body, target_body)

    return current_body


def _apply_rule(rule: dict, current: list | None, original: list) -> list:
    rule = rule.copy()

    result = original
    for identifier, items in rule.items():
        result = _collect_items(identifier, items, result)

    oi = _extract_operation(rule)
    if current is None:
        if oi[0] != MergeLogic.UNION:
            raise ex.ConfigurationError(f"Logical operation `{oi[0]}` is not allowed for the first rule")
        return result
    if oi is None:
        raise ex.ConfigurationError(f"Logical operation not set for current rule")
    operation, identifier = oi
    logger.debug(f"Applying logical operation {operation}...")
    return _operation_method_dict[operation](identifier, result, current)


def _collect_items(
        identifier: KeyValue,
        item_specs: dict[KeyValue, dict | None],
        target_body: list
) -> list:
    """
    Clone and collect without modifying passed `based_specs`
    :param identifier:
    :param item_specs:
    :param target_body:
    :return:
    """
    logger.debug("Normalizing item specifications...")
    item_specs = _normalize_item_specs(identifier, item_specs)
    if item_specs is None:
        return []

    result = []
    found_items = set()
    logger.debug("Making selection...")
    for target_item in target_body:
        id_value = target_item.get(identifier)
        if id_value in item_specs:
            logger.debug(f"Adding item[{id_value}]...")
            overrides = item_specs[id_value]
            clone = _clone(target_item, overrides)
            result.append(clone)
            found_items.add(id_value)

    if len(found_items) != len(item_specs):
        raise ex.ConfigurationError(f"Can't find following items in passed profile: {found_items ^ item_specs.keys()}")
    return result


def _normalize_item_specs(identifier: KeyValue, item_specs: JsonValue) -> dict[KeyValue, dict | None] | None:
    if item_specs is None:
        return None

    if isinstance(item_specs, KeyValue):
        return {item_specs: None}

    result = {}
    if isinstance(item_specs, list):
        if len(item_specs) < 1:
            logger.error("No item defined. Skipping...")
            return None
        if isinstance(item_specs[0], KeyValue):
            for identifier_value in item_specs:
                result[identifier_value] = None
            return result
        else:
            raise ex.ConfigurationError(f"Unexpected item specification type: {type(item_specs[0])}")

    if isinstance(item_specs, dict):
        for identifier_value, overrides in item_specs.items():
            if overrides is None:
                result[identifier_value] = None
            elif isinstance(overrides, KeyValue):
                logger.debug(f"[{identifier_value}] will be renamed to [{overrides}]")
                result[identifier_value] = {identifier: overrides}
            elif isinstance(overrides, dict):
                result[identifier_value] = overrides
                logger.debug(f"[{identifier_value}] content will be overridden to [{str(overrides)}]")
            else:
                raise ex.ConfigurationError(f"Unexpected item override type: {type(overrides)}")
        return result

    raise ex.ConfigurationError(f"Unexpected item specification body type: {type(item_specs)}")


def _check_operation_present(rule: dict[str, JsonValue]) -> bool:
    return _extract_operation(rule) is not None


def _extract_operation(rule: dict[str, JsonValue]) -> tuple[MergeLogic, str] | None:
    """
    tuple( operation, target_identifier )
    :param rule:
    :return:
    """
    result : tuple[MergeLogic, str] | None = None
    for k in MergeLogic:
        if "$" + k not in rule: continue
        if result is not None: raise ex.ConfigurationError("Multiple logical operations defined in one rule")
        result = MergeLogic(k), rule[k]
    return result


def _clone(base_item: JsonValue, override_specs: dict[str, JsonValue] | None) -> JsonValue:
    clone = copy.deepcopy(base_item)
    if override_specs is None:
        return clone
    return helper.recursive_override(override_specs, clone)


def _union(identifier: str, *args: list[dict]) -> list[dict]:
    assert args is not None and len(args) > 1
    union_map = {}
    for dict_list in args:
        for item in dict_list:
            key = item.get(identifier)
            if key is None:
                raise ex.ConfigurationError(f"{identifier} is not present in some items: {str(item)}")
            union_map[key] = item

    return list(union_map.values())


def _difference(identifier: str, *args: list[dict]) -> list[dict]:
    assert args is not None and len(args) > 1

    id_map : dict[str, list[dict | list[dict]]]= {}
    for dict_list in args:
        # Buffer for edge case, where one dict list itself have duplicated identifier value, but not others
        tmp_map : dict[str, dict | list[dict]] = {}
        for d in dict_list:
            id_value = d[identifier]
            if id_value not in tmp_map:
                id_list = []
                tmp_map[id_value] = id_list
            else:
                id_list = tmp_map[id_value]
            id_list.append(d)

        for k, v in tmp_map.items():
            if k not in v:
                id_map[k] = [v]
            else:
                id_map[k].append(v)

    result = []
    for l in id_map.values():
        if len(l) == 1:
            if isinstance(l[0], list):
                result.extend(l[0])
            else:
                result.append(l[0])

    return result


def _intersection(identifier: str, *args: list[dict]) -> list[dict]:
    assert args is not None and len(args) > 1
    id_sets : list[set] = []
    for dict_list in args:
        new_set = set()
        for item in dict_list:
            key = item[identifier]
            new_set.add(key)
        id_sets.append(new_set)

    intersect_ids = set.intersection(*id_sets)
    return [d for d in args[0] if d[identifier] in intersect_ids]


_operation_method_dict : dict[MergeLogic, Callable] = {
    MergeLogic.UNION : _union,
    MergeLogic.DIFFERENCE : _difference,
    MergeLogic.INTERSECTION : _intersection
}