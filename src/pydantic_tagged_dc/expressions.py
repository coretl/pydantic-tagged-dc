from __future__ import annotations

import dataclasses
from abc import abstractmethod
from typing import (
    Annotated,
    Any,
    Generic,
    Literal,
    TypeVar,
    Union,
    get_origin,
    get_type_hints,
)

from pydantic import Discriminator, Field, RootModel, Tag, TypeAdapter
from pydantic.dataclasses import dataclass, rebuild_dataclass
from pydantic.fields import FieldInfo

T = TypeVar("T", int, float)


class _TaggedUnion:
    def __init__(self):
        self._members: set[type] = set()
        self._referrers: dict[type, set[str]] = {}
        self.type_adapter = TypeAdapter(None)

    def add_member(self, cls: type):
        self._members.add(cls)
        subclasses = tuple(Annotated[cls, Tag(cls.__name__)] for cls in self._members)
        if len(subclasses) > 1:
            print("Processing")
            union = Union[subclasses]
            for referrer, fields in self._referrers.items():
                for field in dataclasses.fields(referrer):
                    if field.name in fields:
                        field.type = union
                        field.default.discriminator = Discriminator(_get_type_field)
                print("Referrer", referrer, fields)
                rebuild_dataclass(referrer, force=True)
            self.type_adapter = TypeAdapter(
                Annotated[union, Discriminator(_get_type_field)]  # type: ignore
            )

    def add_referrer(self, cls: type, attr_name: str):
        self._referrers.setdefault(cls, set()).add(attr_name)


def discriminated_union_baseclass(cls):
    cls._tagged_union = _TaggedUnion()
    return dataclass(cls)


def _get_type_field(obj) -> str | None:
    if isinstance(obj, dict):
        return obj.get("type")
    else:
        return getattr(obj, "type", None)


def _get_tagged_union(cls: type) -> _TaggedUnion:
    tu = getattr(cls, "_tagged_union", None)
    if tu and isinstance(tu, _TaggedUnion):
        return tu
    else:
        raise ValueError(
            "Baseclass of {cls} not decorated with @discriminated_union_baseclass"
        )


def _get_ultimate_origin(annotation):
    typ = annotation
    while get_origin(typ) is not None:
        typ = get_origin(typ)
    return typ


def discriminated_union_subclass(cls):
    # Add a discriminator field to the class so it can
    # be identified when deserailizing.
    cls.__annotations__["type"] = Literal[cls.__name__]  # type: ignore
    cls.type = Field(cls.__name__, repr=False)
    # Replace any bare annotation with a discriminated union of subclasses
    # and register this class as one that refers to that union so it can be updated
    for k, v in get_type_hints(cls).items():
        try:
            field_tu = _get_tagged_union(_get_ultimate_origin(v))
        except ValueError:
            # It isn't a tagged union, nothing to do
            pass
        else:
            field_tu.add_referrer(cls, k)
    # Turn it into an actual dataclass
    cls = dataclass(cls)
    # Rebuild any dataclass (including this one) that references this union
    _get_tagged_union(cls).add_member(cls)
    return cls


@discriminated_union_baseclass
class Expression(Generic[T]):
    @abstractmethod
    def calculate(self) -> T:
        raise NotImplementedError(self)

    def serialize(self) -> dict[str, Any]:
        return RootModel(self).model_dump()

    @classmethod
    def deserialize(cls, obj):
        return _get_tagged_union(cls).type_adapter.validate_python(obj)


@discriminated_union_subclass
class Value(Expression[T]):
    value: T = Field(description="Fixed value")

    def calculate(self) -> T:
        return self.value


@discriminated_union_subclass
class Multiply(Expression[T]):
    left: Expression[T] = Field(description="Left hand value of the expression")
    right: Expression[T] = Field(description="Right hand value of the expression")

    def calculate(self) -> T:
        return self.left.calculate() * self.right.calculate()


@discriminated_union_subclass
class Subtract(Expression[T]):
    left: Expression[T] = Field(description="Left hand value of the expression")
    right: Expression[T] = Field(description="Right hand value of the expression")

    def calculate(self) -> T:
        return self.left.calculate() - self.right.calculate()


@discriminated_union_subclass
class Add(Expression[T]):
    left: Expression[T] = Field(description="Left hand value of the expression")
    right: Expression[T] = Field(description="Right hand value of the expression")

    def calculate(self) -> T:
        return self.left.calculate() + self.right.calculate()
