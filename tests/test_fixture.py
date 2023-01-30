from inspect import signature
from typing import List

import pytest
from _pytest.fixtures import SubRequest

from we_love_fixture import fixture


# test a normal fixture
@pytest.fixture
def a():
    return "a"


# test the fixture
@fixture
def b(hi: str = ""):
    return "b" + str(hi)


b_global = b

# test the autoparam feature
c = fixture(test_1="c1", test_2="c2", autoparam=True)


def test_properties():
    assert "request" in dict(signature(b).parameters), "b should have a request object"
    # assert hasattr(b, "__call__"), "fixture should have __call__"
    assert callable(b), f"fixture should be callable"


def test_fixture_a(a: str):
    assert a == "a"


def test_fixture_b(b: str):
    assert b == "b"


def test_mark_is_there():
    assert b.mark, "fixture should have a mark method"


def test_call_is_there():
    assert b.__call__, "fixture should have a __call__ method"


@b.mark(hi="hello")
def test_fixture_b2(b: str):
    assert b == "bhello"


def test_fixture_c(c: str, expects: List[str] = ["c1", "c2"]):
    assert c in expects
    expects.remove(c)
    assert c not in expects


def test_mark_signature():
    sig = signature(b.mark)
    assert sig.parameters["hi"].annotation == str


with pytest.raises(TypeError):

    @b.mark(hi=3)
    def test_fixture_b3(b: str):
        assert b == "b3"


with pytest.raises(TypeError):

    @b.mark(hi="hello", so="what")
    def test_fixture_b_fails_with_TypeError(b: str):
        assert b == "bhello"


class TestFixtures:
    @fixture
    def a(self) -> str:
        return "a"

    @fixture
    def b(self, a: str, request: SubRequest, c: str, d: int = 1) -> str:
        return f"{a}, {c}" * (d or 1)

    assert b is not b_global, "check that b is scoped properly"

    @fixture
    def self_test(self) -> "TestFixtures":
        assert isinstance(self, TestFixtures)
        return self

    def test_fixture_a(self, a: str) -> None:
        assert a == "a"

    def test_fixture_ab(self, b: str, c: str, request: SubRequest, a: str) -> None:
        assert a == "a"
        assert b.startswith(a)
        assert b.endswith(c)

    @b.mark(d=3)
    def test_fixture_abd(self, b: str, c: str, request: SubRequest, a: str) -> None:
        assert a == "a"
        assert b.startswith(a)
        assert b.endswith(c)

    def test_that_self_is_filled_in_correctly(self, self_test: "TestFixtures"):
        assert isinstance(self, TestFixtures)
        assert isinstance(self_test, TestFixtures)
