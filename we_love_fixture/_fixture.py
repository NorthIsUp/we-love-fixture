# External Libraries
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from functools import wraps
from inspect import Parameter, Signature, _empty, _ParameterKind, signature
from optparse import Option
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Dict,
    Generator,
    Iterable,
    List,
    Literal,
    Optional,
    Sequence,
    Type,
    TypedDict,
    TypeVar,
    Union,
    cast,
    overload,
)

import pytest
from _pytest.config import Config
from _pytest.fixtures import FixtureFunctionMarker, SubRequest
from makefun import create_function
from pyparsing import Opt
from xxlimited import foo

T = TypeVar("T")
FixtureFuncT = Callable[..., T]
MarkerFuncT = Callable[..., T]
TestFuncT = Callable[..., None]


# The value of the fixture -- return/yield of the fixture function (type variable).
_FixtureValue = TypeVar("_FixtureValue")

# The type of the fixture function (type variable).
_FixtureFunctionT = Callable[..., object]

# The type of the fixture function (bound variable).
_FixtureFunctionB = TypeVar("_FixtureFunctionB", bound=_FixtureFunctionT)

# The type of a fixture function (type alias generic in fixture value).
_FixtureFunc = Union[
    Callable[..., _FixtureValue], Callable[..., Generator[_FixtureValue, None, None]]
]

# from from _pytest.fixtures import _Scope
_Scope = _Scope = Literal["session", "package", "module", "class", "function"]

FuncT = TypeVar("FuncT", bound=Callable[..., Any])


def _validate_parameter(p: Parameter, arg: object) -> bool:
    if (
        p.name in ("self", "return")
        or p.annotation is _empty
        or (isinstance(p.annotation, type) and isinstance(arg, p.annotation))
        or (
            isinstance(p.annotation, str) and arg.__class__.__name__ == p.annotation
        )  # todo: figure out correct way to check against a string type
    ):  # todo: allow this?
        return True

    msg = f"Argument {p.name!r} <{arg!r}: {arg.__class__.__name__}> is not of type {p.annotation}"
    raise TypeError(msg)


def _validate_input(
    func_sig: Union[Signature, Callable[..., object]], *args: Any, **kwargs: Any
) -> None:
    if callable(func_sig):
        sig = signature(func_sig)
    else:
        sig = func_sig

    params = [p for p in sig.parameters.values() if p.name != "_wl_self"]

    # iterate all type hints
    for p, arg in zip(params, args):
        _validate_parameter(p, arg)

    for p in params[len(args) :]:
        if p.name in ("_wl_self",):
            continue
        _validate_parameter(p, kwargs[p.name])


def _make_class_agnostic(func: FuncT) -> FuncT:
    sig = signature(func)
    if "self" in sig.parameters:

        @wraps(func)
        def wrapper(self: object, *args: Any, **kwargs: Any):
            return func(*args, **kwargs)

        return cast(FuncT, wrapper)
    return func


def _insert_param(
    sig: Signature,
    param: Union[Parameter, str],
    kind: _ParameterKind = Parameter.POSITIONAL_OR_KEYWORD,
    index: int = 0,
) -> Signature:

    if isinstance(param, str):
        param = Parameter(param, kind)

    if param.name in sig.parameters:
        return sig

    params = list(sig.parameters.values())
    params.insert(index, param)

    # keep self at the front
    # for front in ["self", "_wl_self"]:
    #     for i, p in enumerate(params):
    #         if p.name == front:
    #             params.insert(0, params.pop(i))
    #             break

    return sig.replace(parameters=params)


def _remove_param(sig: Signature, param: str) -> Signature:
    return sig.replace(
        parameters=[p for p in sig.parameters.values() if p.name != param]
    )


def _param_index(sig: Signature, name: str, ignore_self: bool = True) -> Optional[int]:
    i: Optional[int] = (
        list(sig.parameters).index(name) if name in sig.parameters else None
    )
    if i and "_wl_self" in sig.parameters:
        i -= 1
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
    scope: "Union[_Scope, Callable[[str, Config], _Scope]]" = "function"
    params: Optional[Iterable[object]] = field(default=None, repr=False)
    autouse: bool = field(default=False, repr=False)
    ids: Optional[
        Union[
            Iterable[Union[None, str, float, int, bool]],
            Callable[[Any], Optional[object]],
        ]
    ] = field(default=None, repr=False)

    args: Sequence[object] = field(default_factory=tuple, repr=False)
    kwargs: Dict[str, object] = field(default_factory=dict, repr=False)

    _fixture: Optional[_FixtureFunctionT] = field(default=None, repr=False)
    _pytestfixturefunction: Optional[FixtureFunctionMarker] = field(
        default=None, repr=False
    )

    def __repr__(self) -> str:
        assert self._fixture, "no fixture is set, this is an error"
        return f"{self.__class__.__name__}(func=<function {self._fixture.__name__}>)"

    @overload
    @classmethod
    def fixture(cls, fixture_function: _FixtureFunctionT) -> WeLoveFixture:
        ...

    @overload
    @classmethod
    def fixture(cls, autoparam: Literal[True], **kwargs: Any) -> WeLoveFixture:
        ...

    @overload
    @classmethod
    def fixture(cls, **kwargs: Any) -> Callable[..., WeLoveFixture]:
        ...

    @classmethod
    def fixture(
        cls, *args: Any, **kwargs: Any
    ) -> Union[WeLoveFixture, Callable[..., WeLoveFixture]]:
        if len(args) == 1 and not kwargs and callable(args[0]):
            # if the function is called as a decorator
            fixture_function: _FixtureFunctionT = args[0]
            return cls().pytest_fixture(fixture_function)

        elif kwargs.pop("autoparam", False):
            # if the function is called as a autoparam

            calling_frame = inspect.stack()[1]
            assert calling_frame, "no frames?"
            calling_module = inspect.getmodule(calling_frame[0])
            assert calling_module, "no module?"

            fixture_name = "gen-fixture"
            try:
                # this is the most hack i have ever hacked, this is terrible but should work for what we need
                # example:
                #   calling_frame.code_context ==  ['c = fixture(test_1=1, test_2=2, autoparam=True)\n']
                if calling_frame.code_context:
                    fixture_name = calling_frame.code_context[0].split("=")[0].strip()
            except Exception:
                pass

            # @_make_class_agnostic
            def _func(request: SubRequest) -> Any:
                return request.param  # type: ignore

            # todo we need to skip the current class
            fixture_function: _FixtureFunctionT = create_function(
                signature(_func),
                _func,
                func_name=fixture_name,
                module_name=calling_module.__name__,
            )

            return cls().pytest_fixture(fixture_function, *args, **kwargs)
        else:
            return cls(*args, **kwargs).pytest_fixture

    @classmethod
    def autoparam(cls, *args: Any, **kwargs: Any) -> WeLoveFixture:
        kwargs["autoparam"] = True
        return cls.fixture(*args, **{**kwargs, "autoparam": True})

    @classmethod
    def _mark_factory(cls, fixture_function: _FixtureFunctionT) -> Callable[..., Any]:
        """generate mark method"""
        assert fixture_function
        fixture_sig: Signature = signature(fixture_function)

        def _mark(**kwargs: Any) -> TestFuncT:
            _validate_input(mark_sig, **kwargs)
            return getattr(pytest.mark, fixture_function.__name__)(**kwargs)

        mark_sig = signature(_mark)
        # mark_self = mark_sig.parameters["self"]
        mark_parameters = tuple(
            p for p in fixture_sig.parameters.values() if p.default is not _empty
        )
        mark_sig = mark_sig.replace(parameters=mark_parameters)
        mark: Callable[..., Any] = create_function(
            mark_sig,
            _mark,
            func_name=f"{fixture_function.__name__}_mark",
            module_name=fixture_function.__module__,
        )
        return mark

    @classmethod
    def _call_factory(cls, fixture_function: _FixtureFunctionT) -> Callable[..., Any]:
        """generate fixture callable"""

        fixture_sig: Signature = signature(fixture_function)
        fixture_self_index = _param_index(fixture_sig, "self")
        fixture_request_index = _param_index(fixture_sig, "request")

        call_sig: Signature
        call_self_index: Optional[int]
        call_request_index: Optional[int]

        def _the_thing(*args: Any, **kwargs: Any) -> Any:
            # raise error if we have a signature mismatch
            print("the thing", args, kwargs)
            _validate_input(call_sig, *args, **kwargs)

            # coalese args and kwargs for parameter indexing
            args_n_kwargs = [*args, *kwargs.values()]

            # pluck the request out
            assert call_request_index is not None
            request = args_n_kwargs[call_request_index]

            mark_kwargs = getattr(
                request.node.get_closest_marker(fixture_function.__name__), "kwargs", {}
            )

            if call_self_index is not None:
                kwargs = {"self": args[call_self_index], **kwargs, **mark_kwargs}
            else:
                kwargs = {**kwargs, **mark_kwargs}

            print(signature(fixture_function), args, kwargs, mark_kwargs)
            if "self" in fixture_sig.parameters:
                kwargs["self"] = None
            return fixture_function(**kwargs)

        # setup call func
        if fixture_self_index is None:
            if fixture_request_index is None:
                # no self, needs request
                def _call(
                    # _wl_self: WeLoveFixture,
                    request: SubRequest,
                    *args: Any,
                    **kwargs: Any,
                ) -> Any:
                    print("no self, needs request", request, args, kwargs)
                    return _the_thing(request, *args, **kwargs)

            else:
                # no self, has request
                def _call(
                    # _wl_self: WeLoveFixture,
                    *args: Any,
                    **kwargs: Any,
                ) -> Any:
                    print("no self, has request", args, kwargs)
                    return _the_thing(*args, **kwargs)

        else:
            # has self
            if fixture_request_index is None:
                # has self, needs request
                def _call(
                    # _wl_self: WeLoveFixture,
                    self: Any,
                    request: SubRequest,
                    *args: Any,
                    **kwargs: Any,
                ) -> Any:
                    print("has self, needs request", locals())
                    return _the_thing(
                        # self,
                        request,
                        *args,
                        **kwargs,
                    )

            else:
                # has self, has request
                def _call(
                    # _wl_self: WeLoveFixture,
                    self: Any,
                    *args: Any,
                    **kwargs: Any,
                ) -> Any:
                    print("has self, has request", locals())
                    return _the_thing(
                        # self,
                        *args,
                        **kwargs,
                    )

        # extract as variable for _validate_input closures above
        call_sig = signature(wraps(fixture_function)(_call))
        call_sig = _insert_param(call_sig, "request")
        # call_sig = _insert_param(call_sig, "_wl_self", index=0)
        # call_sig = _remove_param(call_sig, "self")
        call_self_index = _param_index(call_sig, "self")
        call_request_index = _param_index(call_sig, "request")

        call = create_function(call_sig, _call, func_name=fixture_function.__name__)

        return call

    def pytest_fixture(
        self, fixture_function: _FixtureFunctionT, *args: Any, **kwargs: Any
    ) -> WeLoveFixture:
        if self._fixture:
            return self

        # pop out all args
        scope: _Scope = kwargs.pop("scope", "function")
        autouse: bool = kwargs.pop("autouse", False)
        params: Optional[List[str]] = list(kwargs.pop("params", []))
        ids: Optional[List[str]] = list(kwargs.pop("ids", []))

        # fill params with kwargs + args (in this order)
        params.extend(kwargs.values())
        ids.extend(kwargs.keys())
        params.extend(args)

        call = self._call_factory(fixture_function)
        call.mark = self._mark_factory(fixture_function)

        self._fixture = pytest.fixture(
            scope=scope,
            autouse=autouse,
            params=params or None,
            ids=ids or None,
        )(call)

        assert isinstance(self._fixture._pytestfixturefunction, FixtureFunctionMarker)
        self._pytestfixturefunction = self._fixture._pytestfixturefunction

        return self._fixture


fixture = WeLoveFixture.fixture
