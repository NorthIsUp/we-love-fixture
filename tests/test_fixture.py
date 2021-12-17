from inspect import signature
from typing import List, Optional

import pytest
from we_love_fixture import fixture


# test a normal fixture
@pytest.fixture
def a():
    return "a"


# test the fixture
@fixture
def b(hi: str = ""):
    return "b" + str(hi)


# test the autoparam feature
c = fixture(test_1="c1", test_2="c2", autoparam=True)


def test_fixture_a(a):
    assert a == "a"


def test_fixture_b(b):
    assert b == "b"


@b.mark(hi="hello")
def test_fixture_b2(b):
    assert b == "bhello"


def test_fixture_c(c, expects: list = ["c1", "c2"]):
    assert c in expects
    expects.remove(c)
    assert c not in expects


def test_mark_signature():
    sig = signature(b.mark)
    assert sig.parameters["hi"].annotation == str


with pytest.raises(TypeError):

    @b.mark(hi=3)
    def test_fixture_b3(b):
        assert b == "b3"


with pytest.raises(TypeError):

    @b.mark(hi="hello", so="what")
    def test_fixture_b_fails_with_TypeError(b):
        assert b == "bhello"


class TestFixtures:
    @fixture
    def a(self) -> str:
        return "a"

    @fixture
    def b(self, a, request, c, d: int = 1) -> str:
        return f"{a}, {c}" * (d or 1)

    def test_fixture_a(self, a: str) -> None:
        assert a == "a"

    def test_fixture_ab(self, b, c, request, a) -> None:
        assert a == "a"
        assert b.startswith(a)
        assert b.endswith(c)

    @b.mark(d=3)
    def test_fixture_abd(self, b, c, request, a) -> None:
        assert a == "a"
        assert b.startswith(a)
        assert b.endswith(c)


# l: List[int] = None  # Create empty list with type List[int]
