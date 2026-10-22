"""Serializable copy of a sheet's assembled inputs, so a signed plan can be recalculated without
its sources (spec §8), and a canonical JSON seal for the signed copy."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import types
import typing
from typing import Any

from .sheet import AssembledInputs


def to_jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


def _is_optional(tp) -> tuple[bool, Any]:
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return True, args[0]
    return False, tp


def from_jsonable(tp, data: Any) -> Any:
    if tp is Any or data is None:
        return data
    optional, inner = _is_optional(tp)
    if optional:
        return from_jsonable(inner, data)
    if dataclasses.is_dataclass(tp):
        hints = typing.get_type_hints(tp)
        return tp(**{f.name: from_jsonable(hints[f.name], data[f.name])
                     for f in dataclasses.fields(tp) if f.name in data})
    origin, args = typing.get_origin(tp), typing.get_args(tp)
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(from_jsonable(args[0], v) for v in data)
        return tuple(from_jsonable(a, v) for a, v in zip(args, data, strict=True))
    if origin is list:
        return [from_jsonable(args[0], v) for v in data]
    if origin is dict:
        return {k: from_jsonable(args[1], v) for k, v in data.items()}
    return data


def assembled_to_dict(a: AssembledInputs) -> dict:
    return to_jsonable(a)


def assembled_from_dict(d: dict) -> AssembledInputs:
    return from_jsonable(AssembledInputs, d)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def sha256_of(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()
