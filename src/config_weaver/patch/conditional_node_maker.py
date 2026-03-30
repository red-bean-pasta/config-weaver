from __future__ import annotations

from copy import copy
from typing import Any

from pydantic import BaseModel, create_model

from config_weaver.patch.base.schemas import Select, Filter, Modify, Insert
from config_weaver.patch.base.spec import PatchNode


def make(
        mixin: type[BaseModel],
) -> type[PatchNode]:
    name = f"{_get_prefix(mixin)}{PatchNode.__name__}"

    filter_type, select_type, modify_type, insert_type = tuple(_make_directives(mixin))
    fields = {
        'filter': list[filter_type] | None,
        'select': list[select_type] | None,
        'modify': list[modify_type] | None,
        'insert': list[insert_type] | None,
        'children': f"dict[str, {name}] | None",
    }
    annots = {
        field: _get_field_def(PatchNode, field, annot)
        for field, annot in fields.items()
    }

    cls = create_model(
        name,
        __base__=PatchNode,
        **annots,
    )
    cls.model_rebuild(force=True)
    return cls


def _make_directives(
        mixin: type[BaseModel],
) -> tuple[type[Filter], type[Select], type[Modify], type[Insert]]:
    return tuple(
        _make_model(d, mixin)
        for d in (Filter, Select, Modify, Insert)
    )


def _make_model[T: BaseModel](
        base: type[T],
        mixin: type[BaseModel],
) -> type[T]:
    return type(
        f"{_get_prefix(mixin)}{base.__name__}",
        (base, mixin),
        {}
    )


def _get_prefix(mixin: type[BaseModel]) -> str:
    return mixin.__name__.removesuffix('Mixin')


def _get_field_def(
        base_model: type[BaseModel],
        field_name: str,
        annotation: Any
)-> tuple[Any, Any]:
    info = copy(base_model.model_fields[field_name])
    return annotation, info
