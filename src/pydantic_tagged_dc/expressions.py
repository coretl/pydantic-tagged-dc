from __future__ import annotations

import dataclasses
from abc import abstractmethod
from functools import partial
from typing import Any, Generic, Literal, TypeVar, Union, get_origin, get_type_hints

from pydantic import Field, GetCoreSchemaHandler, RootModel, TypeAdapter
from pydantic.dataclasses import dataclass, rebuild_dataclass
from pydantic.fields import FieldInfo

T = TypeVar("T", int, float)


class _TaggedUnion:
    def __init__(self):
        # The members of the tagged union, i.e. subclasses of the baseclasses
        self._members: set[type] = set()
        # Classes and their field names that refer to this tagged union
        self._referrers: dict[type, set[str]] = {}
        self.type_adapter = TypeAdapter(None)

    def _make_union(self):
        # Make a union of members
        # https://docs.pydantic.dev/2.8/concepts/unions/#discriminated-unions-with-str-discriminators
        if len(self._members) > 1:
            # Unions are only valid with more than 1 member
            return Union[tuple(self._members)]  # type: ignore

    def _set_discriminator(self, cls: type, field_name: str, field: Any):
        # Set the field to use the `type` discriminator on deserialize
        # https://docs.pydantic.dev/2.8/concepts/unions/#discriminated-unions-with-str-discriminators
        assert isinstance(
            field, FieldInfo
        ), f"Expected {cls.__name__}.{field_name} to be a Pydantic field, not {field!r}"
        field.discriminator = "type"

    def add_member(self, cls: type):
        if cls in self._members:
            # A side effect of hooking to __get_pydantic_core_schema__ is that it is
            # called muliple times for the same member, do no process if it wouldn't
            # change the member list
            return
        self._members.add(cls)
        union = self._make_union()
        if union:
            # There are more than 1 subclasses in the union, so set all the referrers
            # to use this union
            for referrer, fields in self._referrers.items():
                for field in dataclasses.fields(referrer):
                    if field.name in fields:
                        field.type = union
                        self._set_discriminator(referrer, field.name, field.default)
                rebuild_dataclass(referrer, force=True)
            # Make a type adapter for use in deserialization
            self.type_adapter = TypeAdapter(union)

    def add_referrer(self, cls: type, attr_name: str):
        self._referrers.setdefault(cls, set()).add(attr_name)
        union = self._make_union()
        if union:
            # There are more than 1 subclasses in the union, so set the referrer
            # (which is currently being constructed) to use it
            # note that we use annotations as the class has not been turned into
            # a dataclass yet
            cls.__annotations__[attr_name] = union
            self._set_discriminator(cls, attr_name, getattr(cls, attr_name, None))


_tagged_unions: dict[type, _TaggedUnion] = {}


def __init_subclass__(cls: type):
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
        # This works for Expression[T] or Expression
        tagged_union = _tagged_unions.get(get_origin(v) or v, None)
        if tagged_union:
            tagged_union.add_referrer(cls, k)


def __get_pydantic_core_schema__(
    cls, source_type: Any, handler: GetCoreSchemaHandler, tagged_union: _TaggedUnion
):
    # Rebuild any dataclass (including this one) that references this union
    # Note that this has to be done after the creation of the dataclass so that
    # previously created classes can refer to this newly created class
    tagged_union.add_member(cls)
    return handler(source_type)


def discriminated_union_of_subclasses(cls):
    tagged_union = _TaggedUnion()
    _tagged_unions[cls] = tagged_union
    cls.__init_subclass__ = classmethod(__init_subclass__)
    cls.__get_pydantic_core_schema__ = classmethod(
        partial(__get_pydantic_core_schema__, tagged_union=tagged_union)
    )
    return cls


@discriminated_union_of_subclasses
class Expression(Generic[T]):
    @abstractmethod
    def calculate(self) -> T:
        raise NotImplementedError(self)

    def serialize(self) -> dict[str, Any]:
        return RootModel(self).model_dump()

    @classmethod
    def deserialize(cls, obj) -> Expression:
        inst = _tagged_unions[Expression].type_adapter.validate_python(obj)
        assert isinstance(inst, cls), "Expected {cls}, got {inst!r}"
        return inst


@dataclass
class Value(Expression[T]):
    value: T = Field(description="Fixed value")

    def calculate(self) -> T:
        return self.value


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


@dataclass
class Subtract(Expression[T]):
    left: Expression[T] = Field(description="Left hand value of the expression")
    right: Expression[T] = Field(description="Right hand value of the expression")

    def calculate(self) -> T:
        return self.left.calculate() - self.right.calculate()
