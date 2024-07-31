from __future__ import annotations

import dataclasses
from abc import abstractmethod
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Generic,
    Literal,
    Protocol,
    TypeVar,
    Union,
    get_origin,
    get_type_hints,
    runtime_checkable,
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
            union = Union[subclasses]  # type: ignore
            # Rebuild in reverse order as we need to rebuild the last added
            # class first so earlier refs will get it
            for referrer, fields in reversed(self._referrers.items()):
                for field in dataclasses.fields(referrer):
                    if field.name in fields:
                        field.type = union
                        assert isinstance(field.default, FieldInfo), (
                            f"Expected {referrer}.{field.name} to be a Pydantic field,"
                            " not {field.default!r}"
                        )
                        field.default.discriminator = Discriminator(_get_type_field)
                rebuild_dataclass(referrer, force=True)
            self.type_adapter = TypeAdapter(
                Annotated[union, Discriminator(_get_type_field)]  # type: ignore
            )

    def add_referrer(self, cls: type, attr_name: str):
        self._referrers.setdefault(cls, set()).add(attr_name)


def _get_type_field(obj) -> str | None:
    if isinstance(obj, dict):
        return obj.get("type")
    else:
        return getattr(obj, "type", None)


@runtime_checkable
class _HasTaggedUnion(Protocol):
    _tagged_union: _TaggedUnion


def _add_to_tagged_union(cls: _HasTaggedUnion) -> _HasTaggedUnion:
    assert isinstance(
        cls, _HasTaggedUnion
    ), "The baseclass of {cls} does not define a '_tagged_union' attribute to add to"
    # Add a discriminator field to the class so it can
    # be identified when deserailizing, and make sure it is last in the list
    cls.__annotations__ = {
        **cls.__annotations__,
        "type": Literal[cls.__name__],  # type: ignore
    }
    cls.type = Field(cls.__name__, repr=False)  # type: ignore
    # Replace any bare annotation with a discriminated union of subclasses
    # and register this class as one that refers to that union so it can be updated
    for k, v in get_type_hints(cls).items():
        # This works for HasTaggedUnion[T] or HasTaggedUnion
        origin = get_origin(v) or v
        if isinstance(origin, _HasTaggedUnion):
            origin._tagged_union.add_referrer(cls, k)
    # Turn it into an actual dataclass
    cls = dataclass(cls)
    # Rebuild any dataclass (including this one) that references this union
    # Note that this has to be done after the creation of the dataclass so that
    # previously created classes can refer to this newly created class
    cls._tagged_union.add_member(cls)
    return cls


if TYPE_CHECKING:
    # From the type checker's point of view we are making a regular pydantic dataclass
    add_to_tagged_union = dataclass
else:
    # But at runtime need to do some work to make the tagged union
    add_to_tagged_union = _add_to_tagged_union


@dataclass
class Expression(_HasTaggedUnion, Generic[T]):
    _tagged_union = _TaggedUnion()

    @abstractmethod
    def calculate(self) -> T:
        raise NotImplementedError(self)

    def serialize(self) -> dict[str, Any]:
        return RootModel(self).model_dump()

    @classmethod
    def deserialize(cls, obj):
        return cls._tagged_union.type_adapter.validate_python(obj)


@add_to_tagged_union
class Value(Expression[T]):
    value: T = Field(description="Fixed value")

    def calculate(self) -> T:
        return self.value


@add_to_tagged_union
class Multiply(Expression[T]):
    left: Expression[T] = Field(description="Left hand value of the expression")
    right: Expression[T] = Field(description="Right hand value of the expression")

    def calculate(self) -> T:
        return self.left.calculate() * self.right.calculate()


@add_to_tagged_union
class Add(Expression[T]):
    left: Expression[T] = Field(description="Left hand value of the expression")
    right: Expression[T] = Field(description="Right hand value of the expression")

    def calculate(self) -> T:
        return self.left.calculate() + self.right.calculate()


@add_to_tagged_union
class Subtract(Expression[T]):
    left: Expression[T] = Field(description="Left hand value of the expression")
    right: Expression[T] = Field(description="Right hand value of the expression")

    def calculate(self) -> T:
        return self.left.calculate() - self.right.calculate()
