from __future__ import annotations

import dataclasses
from abc import abstractmethod
from functools import partial
from typing import (
    Annotated,
    Any,
    Generic,
    Iterator,
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

# baseclass -> referring dataclass -> set of fields that refer to union of subclasses
_baseclass_referrers: dict[type, dict[type, set[str]]] = {}
# type adapters for each baseclass
_typeadapters: dict[type, TypeAdapter] = {}


def discriminated_union_of_subclasses(cls):
    _baseclass_referrers[cls] = {}
    cls.__init_subclass__ = classmethod(partial(__init_subclass__, baseclass=cls))
    return cls


def _get_ultimate_origin(annotation):
    typ = annotation
    while get_origin(typ) is not None:
        typ = get_origin(typ)
    return typ


def _recursive_subclasses(cls: type) -> Iterator[type]:
    for subcls in cls.__subclasses__():
        yield subcls
        yield from _recursive_subclasses(subcls)


def _make_tagged_union(baseclass: type):
    subclasses = tuple(
        Annotated[x, Tag(x.__name__)] for x in _recursive_subclasses(baseclass)
    )
    if len(subclasses) > 1:
        return Union[subclasses]  # type: ignore


def _get_type_field(obj) -> str | None:
    if isinstance(obj, dict):
        return obj.get("type")
    else:
        return getattr(obj, "type", None)


def __init_subclass__(cls, baseclass) -> None:
    # Add a discriminator field to the class so it can
    # be identified when deserailizing.
    cls.__annotations__ = {
        **cls.__annotations__,
        "type": Literal[cls.__name__],  # type: ignore
    }
    cls.type = Field(cls.__name__, repr=False)
    # Rebuild any dataclass that references this union
    union = _make_tagged_union(baseclass)
    for referrer, fields in _baseclass_referrers[baseclass].items():
        for field in dataclasses.fields(referrer):
            if field.name in fields:
                field.type = union
        rebuild_dataclass(referrer, force=True)
    # Add a cached TypeAdapter for deserialization
    _typeadapters[baseclass] = TypeAdapter(
        Annotated[union, Discriminator(_get_type_field)]  # type: ignore
    )
    # Replace any bare annotation with a discriminated union of subclasses
    for k, v in get_type_hints(cls).items():
        origin = _get_ultimate_origin(v)
        if origin in _baseclass_referrers:
            cls.__annotations__[k] = _make_tagged_union(origin)
            field = getattr(cls, k, None)
            assert isinstance(
                field, FieldInfo
            ), f"Expected {cls}.{k} to be a pydantic Field, got {type(field)}"
            field.discriminator = Discriminator(_get_type_field)
            _baseclass_referrers[origin].setdefault(cls, set()).add(k)


@discriminated_union_of_subclasses
@dataclass
class Expression(Generic[T]):
    @abstractmethod
    def calculate(self) -> T:
        raise NotImplementedError(self)

    def serialize(self) -> dict[str, Any]:
        return RootModel(self).model_dump()

    @classmethod
    def deserialize(cls, obj):
        return _typeadapters[Expression].validate_python(obj)


@dataclass
class Value(Expression[T]):
    value: T = Field(description="Fixed value")

    def calculate(self) -> T:
        return self.value


@dataclass
class Subtract(Expression[T]):
    left: Expression[T] = Field(description="Left hand value of the expression")
    right: Expression[T] = Field(description="Right hand value of the expression")

    def calculate(self) -> T:
        return self.left.calculate() - self.right.calculate()


@dataclass
class Multiply(Expression[T]):
    left: Expression[T] = Field(description="Left hand value of the expression")
    right: Expression[T] = Field(description="Right hand value of the expression")

    def calculate(self) -> T:
        return self.left.calculate() * self.right.calculate()


@dataclass
class Add(Expression[T]):
    left: Expression[T] = Field(description="Left hand value of the expression")
    right: Expression[T] = Field(description="Right hand value of the expression")

    def calculate(self) -> T:
        return self.left.calculate() + self.right.calculate()
