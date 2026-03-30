from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

import config_weaver.patch.base.filter as strain
from config_weaver.utils.json_helper import JsonValue, as_list
from config_weaver.patch.base import selector, modifier, inserter
from config_weaver.patch.base.schemas import Select, Filter, Modify, Insert


class PatchNode(BaseModel):
    model_config = ConfigDict(
        validate_by_name=True,
        validate_by_alias=True,
        extra='forbid'
    )

    filter: list[Filter] | None = Field(default=None, alias='$filter')
    select: list[Select] | None = Field(default=None, alias='$select')
    modify: list[Modify] | None = Field(default=None, alias='$modify')
    insert: list[Insert] | None = Field(default=None, alias='$insert')

    children: dict[str, PatchNode] = Field(default_factory=dict, alias='$children')

    @model_validator(mode='before')
    @classmethod
    def _split_children(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        children: dict[str, Any] = {}
        normalized: dict[str, Any] = {}
        for key, value in data.items():
            if key in ['$filter', '$select', '$modify', '$insert']:
                normalized[key] = value
            else:
                children[key] = value
        if children:
            normalized['$children'] = children

        return normalized

    @field_validator('select', 'filter', 'modify', 'insert', mode='before')
    @classmethod
    def _normalize_single_field(cls, value) -> list[JsonValue] | None:
        return as_list(value)

    ordered_directives: dict[str, Callable[[list[BaseModel], JsonValue], JsonValue]] = {
        'filter': strain.apply_filters,
        'select': selector.apply_selects,
        'modify': modifier.apply_modifies,
        'insert': inserter.apply_inserts,
    }
    def patch(self, target: JsonValue) -> JsonValue:
        result = target
        for directive, func in self.ordered_directives.items():
            if values := getattr(self, directive):
                result = func(values, result)
        for key, child in self.children.items():
            result[key] = child.patch(result[key])
        return result