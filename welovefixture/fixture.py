# External Libraries
from __future__ import annotations
import inspect
from dataclasses import dataclass, field
from functools import partial, wraps
from inspect import Parameter, Signature, _empty, _ParameterKind, cleandoc, signature
from itertools import chain
from textwrap import wrap
from types import FunctionType, MethodType
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Type, TypeVar, Union, cast, get_type_hints

import pytest
from _pytest.compat import cached_property
from _pytest.fixtures import Config, SubRequest, _FixtureFunction

from welovefixture.makefun import create_function
from welovefixture.util import make_class_agnostic, deep_make_class_agnostic, make_class_agnostic2

T = TypeVar("T")
FixtureFuncT = Callable[..., T]
MarkerFuncT = Callable[..., T]
TestFuncT = Callable[..., None]

if TYPE_CHECKING:
    from _pytest.fixtures import _Scope


def _requires_fixture_function(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if self.fixture_function is None:
            raise ValueError(f"'fixture_function' must be set before calling '{func.__name__}'")
        return func(self, *args, **kwargs)

    return wrapper


def _validate_parameter(p: Parameter, arg: object) -> bool:
    if p.name in ("self", "return") or p.annotation is _empty or isinstance(arg, p.annotation):  # todo: allow this?
        return True

    msg = f"Argument {p.name!r} <{arg!r}: {arg.__class__.__name__}> is not of type {p.annotation}"
    raise TypeError(msg)


def _validate_input(func_sig: Union[Signature, Callable[..., object]], *args, **kwargs) -> None:
    if callable(func_sig):
        sig = signature(func_sig)
    else:
        sig = cast(Signature, func_sig)

    params = list(sig.parameters.values())

    # iterate all type hints
    for p, arg in zip(params, args):
        _validate_parameter(p, arg)

    for p in params[len(args) :]:
        _validate_parameter(p, kwargs[p.name])


def _make_class_agnostic(func):
    sig = signature(func)
    if sig.parameters.get("self"):

        @wraps(func)
        def wrapper(self, *args, **kwargs):
            return func(*args, **kwargs)

        return wrapper
    return func


def _insert_param(sig: Signature, param: Parameter, index=0):
    params = list(sig.parameters.values())
    params.insert(index, param)
    return sig.replace(parameters=params)


def _insert_self_param(sig: Signature) -> Signature:
    if "self" not in sig.parameters:
        param = Parameter("self", _ParameterKind.POSITIONAL_OR_KEYWORD)
        sig = _insert_param(sig, param)
    return sig


def _insert_request_param(sig: Signature) -> Signature:
    if "request" not in sig.parameters:
        index = 1 if "self" in sig.parameters else 0

        param = Parameter("request", _ParameterKind.POSITIONAL_OR_KEYWORD, annotation=SubRequest)
        sig = _insert_param(sig, param, index)
    return sig


def _param_index(sig: Signature, name: str) -> Optional[int]:
    i: Optional[int] = list(sig.parameters).index(name) if name in sig.parameters else None
    return i


@dataclass
class WeLoveFixture:
    """
    @WeLoveFixture()
    def user(
        posts,  # posts is a fixture
        email: Optional[str]=None  # email is a marker
        ) -> User:
        return UserFactory(posts=posts, email=email)

    @user.mark(email='hi@example.com')
    def test_user(user):
        assert user.email == 'hi@example.com'
    """

    # match the pytest fixture types
    fixture_function: Optional[_FixtureFunction] = None
    scope: "Union[_Scope, Callable[[str, Config], _Scope]]" = "function"
    params: Optional[Iterable[object]] = None
    autouse: bool = False
    ids: Optional[
        Union[
            Iterable[Union[None, str, float, int, bool]],
            Callable[[Any], Optional[object]],
        ]
    ] = None

    args: Sequence[object] = field(default_factory=tuple)
    kwargs: Dict[str, object] = field(default_factory=dict)

    _fixture: Optional[_FixtureFunction] = None

    @classmethod
    def fixture(cls, *args, **kwargs) -> Union[_FixtureFunction, Callable[[_FixtureFunction], _FixtureFunction]]:
        if len(args) == 1 and not kwargs and callable(args[0]):
            # if the function is called as a decorator
            return cls(args[0]).pytest_fixture()
        elif kwargs.pop("autoparam", False):
            # if the function is called as a autoparam

            calling_frame = inspect.stack()[1]
            calling_module = inspect.getmodule(calling_frame[0])

            try:
                # this is the most hack i have ever hacked, this is terrible but should work for what we need
                # example:
                #   calling_frame.code_context ==  ['c = fixture(test_1=1, test_2=2, autoparam=True)\n']
                fixture_name = calling_frame.code_context[0].split("=")[0].strip()
            except Exception:
                fixture_name = "gen-fixture"

            @_make_class_agnostic
            def func(request):
                return request.param

            # todo we need to skip the current class
            func = create_function(
                signature(func),
                func,
                func_name=fixture_name,
                module_name=calling_module.__name__,
            )

            return cls(func).pytest_fixture(*args, **kwargs)
        else:
            return cls(*args, **kwargs).wrapper

    @classmethod
    def autoparam(cls, *args, **kwargs) -> Union[_FixtureFunction, Callable[[_FixtureFunction], _FixtureFunction]]:
        kwargs["autoparam"] = True
        return cls.fixture(*args, **kwargs)

    @cached_property
    @_requires_fixture_function
    def name(self) -> str:
        assert self.fixture_function
        return self.fixture_function.__name__

    @_requires_fixture_function
    def mark(self) -> Callable[..., Any]:
        """generate mark method"""
        assert self.fixture_function
        fixture_sig: Signature = signature(self.fixture_function)

        def _mark(**kwargs) -> TestFuncT:
            _validate_input(mark_sig, **kwargs)
            return getattr(pytest.mark, self.name)(**kwargs)

        mark_sig = signature(_mark)
        mark_parameters = tuple(p for p in fixture_sig.parameters.values() if p.default is not _empty)
        mark_sig = mark_sig.replace(parameters=mark_parameters)
        mark = create_function(
            mark_sig,
            _mark,
            func_name=f"{self.name}_mark",
            module_name=self.fixture_function.__module__,
        )
        return mark

    @_requires_fixture_function
    def call(self) -> Callable[..., Any]:
        """generate fixture callable"""
        assert self.fixture_function

        fixture_sig: Signature = signature(self.fixture_function)
        fixture_self_index = _param_index(fixture_sig, "self")
        fixture_request_index = _param_index(fixture_sig, "request")

        call_sig: Signature
        call_self_index: Optional[int]
        call_request_index: Optional[int]

        fixture_function = self.fixture_function

        def _the_thing(*args, **kwargs):
            # raise error if we have a signature mismatch
            _validate_input(call_sig, *args, **kwargs)

            # coalese args and kwargs for parameter indexing
            args_n_kwargs = [*args, *kwargs.values()]

            # pluck the request out
            request = args_n_kwargs[call_request_index]
            mark_kwargs = getattr(request.node.get_closest_marker(self.name), "kwargs", {})

            if call_self_index is not None:
                kwargs = {"self": args[call_self_index], **kwargs, **mark_kwargs}
            else:
                kwargs = {**kwargs, **mark_kwargs}

            # print(signature(fixture_function), args, kwargs, mark_kwargs)
            return fixture_function(**kwargs)

        # setup call func
        if fixture_self_index is None:
            if fixture_request_index is None:
                # no self, needs request
                def _call(request, *args, **kwargs):
                    # print("no self, needs request", args, kwargs)
                    return _the_thing(request, *args, **kwargs)

            else:
                # no self, has request
                def _call(*args, **kwargs):
                    # print("no self, has request", args, kwargs)
                    return _the_thing(*args, **kwargs)

        else:
            # has self
            if fixture_request_index is None:
                # has self, needs request
                def _call(self, request, *args, **kwargs):
                    # print("has self, needs request", args, kwargs)
                    return _the_thing(self, request, *args, **kwargs)

            else:
                # has self, has request
                def _call(self, *args, **kwargs):
                    # print("has self, has request", args, kwargs)
                    return _the_thing(self, *args, **kwargs)

        # extract as variable for _validate_input closures above
        call = wraps(self.fixture_function)(_call)

        call_sig = _insert_request_param(signature(call))
        call_self_index = _param_index(call_sig, "self")
        call_request_index = _param_index(call_sig, "request")
        assert call_request_index is not None

        call = create_function(call_sig, _call, func_name=self.name)

        return call

    def wrapper(self, fixture_function: _FixtureFunction) -> _FixtureFunction:
        self.fixture_function = fixture_function
        return self.pytest_fixture()

    def pytest_fixture(self, *args, **kwargs) -> _FixtureFunction:
        if self._fixture:
            return self._fixture

        fixture_kwargs = {}
        if "scope" in kwargs:
            fixture_kwargs["scope"] = kwargs.pop("scope")

        if "autouse" in kwargs:
            fixture_kwargs["autouse"] = kwargs.pop("autouse")

        if "params" in kwargs:
            fixture_kwargs["params"] = list(kwargs.pop("params"))

        if "ids" in kwargs:
            fixture_kwargs["ids"] = list(kwargs.pop("ids"))

        if kwargs:
            fixture_kwargs.setdefault("params", []).extend(kwargs.values())
            fixture_kwargs.setdefault("ids", []).extend(kwargs.keys())

        if args:
            fixture_kwargs.setdefault("params", []).extend(args)

        call = self.call()
        call.mark = self.mark()
        self._fixture = pytest.fixture(**fixture_kwargs)(call)

        return self._fixture


fixture = WeLoveFixture.fixture


# def fixture(*args, **kwargs):
#     """
#     Same args and kwargs as pytest.fixture with the following additions.
#     Args:
#         autoparam (bool): Instead of operating as a decorator just automatically create a fixture that returns `request.param`
#         **kwargs: kwargs is automatically converted to id, param pairs for the purpose of parametrized tests.
#     Returns: a pytest.fixture function or method.
#     """

#     def decorator_factory(func):
#         fixture_kwargs = {}
#         if "scope" in kwargs:
#             fixture_kwargs["scope"] = kwargs.pop("scope")

#         if "autouse" in kwargs:
#             fixture_kwargs["autouse"] = kwargs.pop("autouse")

#         if "params" in kwargs:
#             fixture_kwargs["params"] = list(kwargs.pop("params"))

#         if "ids" in kwargs:
#             fixture_kwargs["ids"] = list(kwargs.pop("ids"))

#         if kwargs:
#             fixture_kwargs.setdefault("params", []).extend(kwargs.values())
#             fixture_kwargs.setdefault("ids", []).extend(kwargs.keys())

#         if args:
#             fixture_kwargs.setdefault("params", []).extend(args)

#         return pytest.fixture(**fixture_kwargs)(func)

#     if len(args) == 1 and not kwargs and callable(args[0]):
#         # if the function is called as a decorator
#         function_to_wrap = args[0]
#         args = ()
#     elif kwargs.pop("autoparam", False):
#         # if the function is called as a autoparam
#         @make_class_agnostic
#         def function_to_wrap(request):
#             return request.param

#     else:
#         function_to_wrap = None

#     if function_to_wrap:
#         return decorator_factory(function_to_wrap)
#     else:
#         return decorator_factory
