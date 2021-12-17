from __future__ import absolute_import

# Standard Library
from functools import wraps
from types import FunctionType
from unittest import mock

# External Libraries
import pytest

# Project Library
from lindy.core.importlib import import_class
from lindy.core.text import trim


def parametrize(**kwargs):
    def decorator_factory(func):
        for key, value in kwargs.items():
            if isinstance(value, (list, tuple)):
                func = pytest.mark.parametrize(key, value)(func)
            else:
                func = pytest.mark.parametrize(key, [value])(func)
        return func

    return decorator_factory
