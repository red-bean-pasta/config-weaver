import json
import logging
from json import JSONEncoder
from typing import Union, Iterable

from sailor_tailor import exceptions as ex


logger = logging.getLogger(__name__)

JsonValue = Union[dict, list, str, int, float, bool, None]

FieldValue = Union[str, list, dict]


class SetEncoder(JSONEncoder):
    def default(self, obj):
        return list(obj) if isinstance(obj, set) else super().default(obj)


def get_readable_dump(v: dict, encoder: type[JSONEncoder] | None = None) -> str:
    return json.dumps(v, indent=4, ensure_ascii=False, cls = encoder)


def override_merge_dict(*args: dict | None) -> dict | None:
    """
    {key: value_1} + {key: value_2} = {key: value_2}
    :param args:
    :return:
    """
    result = None
    for d in args:
        if result is None:
            result = d
        elif d is None:
            continue
        else:
            result |= d
    return result


def union_merge_dict(augend: dict, addend: dict) -> dict:
    """
    {key: value_1} + {key: value_2} = {key: [value_1, value_2]}
    :param augend:
    :param addend:
    :return:
    """
    for k, v in addend.items():
        if v is None:
            continue
        if k not in augend or augend[k] is None:
            augend[k] = v
            continue
        t = augend[k]
        if isinstance(t, dict) and isinstance(v, dict):
            augend[k] = union_merge_dict(t, v)
        elif not isinstance(t, dict) and not isinstance(v, dict):
            augend[k] = merge_values_as_list(t, v)
        else:
            raise ValueError(f"Trying to merge {type(t)} with {type(v)}")
    return augend


def recursive_override(overrides: dict[str, JsonValue], target: dict[str, JsonValue]) -> dict[str, JsonValue]:
    for k, v in overrides.items():
        if k not in target:
            target[k] = v
            continue

        if not isinstance(v, dict): # Whether v is null, array or string
            if isinstance(target[k], dict):
                logger.warning(f"Overriding object value with non-object: \n{k}: {target[k]}\n=>\n{k}: {v} ")
            target[k] = v  # Add or override
            continue

        t = target[k] # target
        if isinstance(t, dict):
            recursive_override(v, t)
        else:
            logger.warning(f"Overriding non-object value with object: \n{k}: {t}\n=>\n{k}: {v}")
            target[k] = v

    return target


def get_with_aliases(
        keys: list[str] | str,
        rule: dict[str, JsonValue],
        tolerated_typos: list[str] | str | None
) -> tuple[str, JsonValue] | None:
    ok = to_list(keys)
    alright = to_list(tolerated_typos)
    together = merge_values_as_list(ok, alright)
    matched = _try_find_with_aliases(together, rule)
    if not matched:
        return None
    if matched in alright:
        logger.warning(f"Found '{matched}'. Do you mean '{ok[-1]}'?")
    return matched, rule[matched]


def get_unspecified_key_value_pairs(target: dict, *specified: tuple[str, JsonValue] | None) -> dict[str, JsonValue]:
    if specified is None or len(specified) == 0:
        return target
    specified_keys = {s[0] for s in specified if s is not None}
    unspecified_keys = target.keys() - specified_keys
    return {k: target[k] for k in unspecified_keys if k in target}


def get_unspecified_keys(target: dict, *specified: str | None) -> set[str]:
    return target.keys() - set() if specified is None else {s for s in specified if s is not None}


def merge_values_as_list(augend, addend) -> list:
    """
    Doesn't modify any argument
    :param augend:
    :param addend:
    :return:
    """
    if addend is None:
        return augend
    if augend is None:
        return addend

    l = augend if isinstance(augend, list) else addend if isinstance(addend, list) else []
    i = to_list(addend) if l is augend else [augend] if l is addend else [augend, addend]

    lt = type(l[0]) if len(l) > 0 else type(i[0])
    io = i[0] if len(l) > 0 else i[1]
    if not isinstance(io, lt):
        raise ValueError(f"Trying to merge list[{lt}] with list[{type(io)}]")

    result = list(l)
    result.extend(i) # avoid modifying existing values
    return result


def get_invalid_type_log(field: str, value_type: type | str) -> str:
    return f"'{field}' is of invalid type: {value_type}"


def as_list(x: JsonValue) -> list[JsonValue] | None:
    """
    None is kept as is
    :param x:
    :return:
    """
    if x is None:
        return None
    if isinstance(x, list):
        return list(x) # Shallow copy
    return [x]


def to_list(v) -> list:
    """
    None is converted to []
    :param v:
    :return:
    """
    return list(v) if isinstance(v, list) else [v] if v is not None else []


def to_set(v) -> set:
    if v is None:
        return set()
    if isinstance(v, str):
        return {v}
    if isinstance(v, Iterable):
        return set(v)
    return {v}


def _try_find_with_aliases(
        key: str | set[str] | list[str],
        dic: dict[str, JsonValue],
        exclusive: bool = True
) -> str | None:
    """

    :param key:
    :param dic:
    :param exclusive: If false, the first match will be returned
    :return:
    """
    assert isinstance(key, str | set | list)
    found = None
    for k in to_set(key):
        if k not in dic:
            continue
        if not exclusive:
            return k
        if not found:
            found = k
            continue
        raise ex.ConfigurationError(f"Key duplicates found: '{k}', '{found}'")
    return found
