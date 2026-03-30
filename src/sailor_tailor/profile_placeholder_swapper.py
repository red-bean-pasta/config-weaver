
from sailor_tailor.json_helper import JsonValue


def recursive_replace_token(element: JsonValue, token: str, value: str, replace_keys: bool = False) -> object:
    """
    Doesn't modify on passed element
    :param element:
    :param token:
    :param value:
    :param replace_keys:
    :return:
    """
    if isinstance(element, str):
        return value if element == token else element
    if isinstance(element, list):
        return [recursive_replace_token(e, token, value, replace_keys) for e in element]
    if isinstance(element, dict):
        new_dict = {}
        for k, v in element.items():
            new_key = (value if replace_keys and k == token else k)
            new_dict[new_key] = recursive_replace_token(v, token, value, replace_keys)
        return new_dict
    return element # null, true, false