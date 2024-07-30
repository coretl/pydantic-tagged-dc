from pytest import fixture

from pydantic_tagged_dc.expressions import Add, Expression, Subtract, Value


@fixture
def expression():
    yield Subtract(Add(Value(2), Value(4)), Value(3))


@fixture
def serialized():
    yield (
        {
            "left": {
                "left": {"value": 2, "type": "Value"},
                "right": {"value": 4, "type": "Value"},
                "type": "Add",
            },
            "right": {"value": 3, "type": "Value"},
            "type": "Subtract",
        }
    )


def test_serialize(expression: Expression, serialized: dict):
    assert expression.serialize() == serialized


def test_deserialize(expression: Expression, serialized: dict):
    assert Expression.deserialize(serialized) == expression


def test_render(expression: Expression):
    assert (
        str(expression)
        == "Subtract(left=Add(left=Value(value=2), right=Value(value=4)),"
        " right=Value(value=3))"
    )
