import inspect
from pprint import pprint
from types import MethodType
from typing import Optional
from functools import wraps


def is_inside_class(depth=0) -> Optional[str]:
    """
    Returns: Class name of encapsulating class or None
    """
    frames = inspect.stack()
    for frame in frames[depth + 1 :]:
        if frame[3] == "<module>":
            # At module level, go no further
            break
        elif "__module__" in frame[0].f_code.co_names:
            # found the encapsulating class, go no further
            print("yep", frame[0].f_code.co_name)
            return frame[0].f_code.co_name
    print("nope")
    return None


def make_class_agnostic(func, depth=0):
    """
    make fixtures that don't care if it is in a class or not work fine
    >>> @make_class_agnostic
    ... def inner_func(request):
    ...     return request
    ...
    >>> class Foo():
    ...     bar = inner_func
    ...
    >>> Foo.bar('hi') == 'hi'
    True
    >>> inner_func('hi') == 'hi'
    True
    """

    if is_inside_class(depth=depth):

        def wrapper(self, request):
            return func(request)

    else:

        def wrapper(request):
            return func(request)

    return wrapper


def make_class_agnostic2(func):
    if isinstance(func, MethodType):

        def wrapper(self, request):
            return func(request)

    else:

        def wrapper(request):
            return func(request)

    return wraps(func)(wrapper)


def deep_make_class_agnostic(depth=0):
    def decorator(func):
        return make_class_agnostic(func, depth=depth)

    return decorator
