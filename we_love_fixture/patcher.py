from __future__ import absolute_import

from functools import wraps
from types import FunctionType
from unittest import mock

import pytest

from inspect import cleandoc


def patcher(path_or_obj, key=None, raising=False, autouse=True, automock=False, automagicmock=False, configure_mock=None, **mock_args):
    """A helper function for using monkeypatch with py.test
    patcher can be used as a decorator or a function.
    Args:
        path_or_obj: A string of a python path to patch or an object to patch
        key: If an object is provided, this is the name of the attribute to patch
        raising: Raise an exception if the attribute to patch does not already exits
        autouse: If True the patch will happen automatically for every test in the scope,
            otherwise it must be passed in as a pytest fixture.
        automock: Automatically return a Mock object
        automagicmock: Automatically return a MagicMock object
        dict configure_mock: If automock or automagicmock is enabled then pass this dict to mock.configure_mock
        return_value: If automock and automagicmock are False, then simply return this value.
            If they are true then return_value is passed normally to the mock class.
        **mock_args: Args to be passed into mock_class(**mock_args)
    Returns pytest.fixture: a vailid pytest fixture function
    Examples:
        As a simple decorator with a path to patch. Similar to mock.patch
        >>> @patcher('path.to.func')
        ... def patcher_func():
        ...     return 'hello'
        >>> # Equivalent to:
        >>> patcher_func = patcher('path.to.func', return_value='hello')
        >>> # Note that there is no way to use fixture arguments when using patcher in this example
        As a simple decorator with an object to patch. This will replace
          `class_to_patch.attribute` with the return value of patcher_func
        >>> class SomeClass():
        ...     def foo(self): pass
        >>> @patcher(SomeClass, 'foo')
        ... def patcher_func(any, fixture, you, want):
        ...     return lambda self: 'hi'
        This example will fail if `SomeClass.attribute` does not already exist
        >>> @patcher(SomeClass, 'attribute', raising=True)
        ... def patcher_func(any, fixture, you, want):
        ...     return lambda self: 'hi'
    """

    def decorator_factory(func):
        """
        py.test introsepects the names of arguments in functions to pass in fixtures
        This means we need to dynamically construct the inner call to `func` to contain
        these names.
        """
        from _pytest.compat import getfuncargnames

        args = getfuncargnames(func)

        monkey_args = set(args + ("monkeypatch",))

        wrapper_str = cleandoc(
            """
        @pytest.fixture(autouse={autouse})
        def {fixture_name}({monkey_args}):
            val = func({args})
            if isinstance(path_or_obj, str):
                monkeypatch.setattr(path_or_obj, val, raising=raising)
            elif isinstance(path_or_obj, (tuple, list)):
                for item in path_or_obj:
                    monkeypatch.setattr(item, val, raising=raising)
            else:
                monkeypatch.setattr(path_or_obj, key, value=val, raising=raising)
            return val
        """
        ).format(fixture_name=func.__name__, args=", ".join(args), monkey_args=", ".join(monkey_args), autouse=repr(autouse))

        # Execute the template string in a temporary namespace and support
        # tracing utilities by setting a value for frame.f_globals['__name__']
        namespace = {
            "func": func,
            "key": key,
            "path_or_obj": path_or_obj,
            "pytest": pytest,
            "raising": raising,
            "wraps": wraps,
            "__name__": "patcher_%s" % func.__name__,
        }
        exec(wrapper_str, namespace)
        return namespace[func.__name__]

    if automock or automagicmock or configure_mock:

        @make_class_agnostic
        def _func(*args):
            # creation of the mock object must be scoped in this _func
            mock_class = None
            if automock:
                mock_class = mock.Mock
            elif automagicmock:
                mock_class = mock.MagicMock

            mock_instance = mock_class(**mock_args)
            if configure_mock:
                mock_instance.configure_mock(**configure_mock)

            return mock_instance

        return decorator_factory(_func)

    elif "return_value" in mock_args:
        return_value = mock_args.pop("return_value")

        @make_class_agnostic
        def _func(*args):
            return return_value

        return decorator_factory(_func)

    return decorator_factory
