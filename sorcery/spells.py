import ast
import operator
import sys
from pprint import pprint

import wrapt

from sorcery.core import spell

_NO_DEFAULT = object()


@spell
def unpack_keys(frame_info, x, default=_NO_DEFAULT):
    return _unpack(frame_info, x,
                   operator.getitem if default is _NO_DEFAULT else
                   lambda d, name: d.get(name, default))


@spell
def unpack_attrs(frame_info, x):
    return _unpack(frame_info, x, getattr)


def _unpack(frame_info, x, getter):
    names, node = frame_info.assigned_names
    if isinstance(node, ast.Assign):
        return [getter(x, name) for name in names]
    else:  # for loop
        return ([getter(d, name) for name in names]
                for d in x)


@spell
def args_with_source(frame_info, args):
    tokens = frame_info.file_info.tokens
    return [
        (tokens.get_text(arg), value)
        for arg, value in zip(frame_info.call.args, args)
    ]


@spell
def dict_of(frame_info, *args, **kwargs):
    result = {
        arg.id: value
        for arg, value in zip(frame_info.call.args, args)
    }
    result.update(kwargs)
    return result


@spell
def print_args(frame_info, *args):
    for source, arg in args_with_source[frame_info](args):
        print(source + ' =')
        pprint(arg)
        print()
    return args and args[0]


@spell
def call_with_name(frame_info, func):
    def make_func(name):
        return lambda self, *args, **kwargs: func(self, name, *args, **kwargs)

    return [
        make_func(name)
        for name in frame_info.assigned_names[0]
    ]


@spell
def delegate_to_attr(frame_info, attr_name):
    def make_func(name):
        return property(lambda self: getattr(getattr(self, attr_name), name))

    return [
        make_func(name)
        for name in frame_info.assigned_names[0]
    ]


def magic_kwargs(func):
    @wrapt.decorator
    def wrapper(wrapped, _instance, args, kwargs):
        # if instance is not None:
        #     raise TypeError('magic_kwargs can only be applied to free functions, not methods')
        full_kwargs = dict_of[args[0]](*args[1:], **kwargs)
        return wrapped(**full_kwargs)

    return spell(wrapper(func))


class Module(object):
    unpack_keys = unpack_keys
    unpack_attrs = unpack_attrs
    args_with_source = args_with_source
    dict_of = dict_of
    print_args = print_args
    call_with_name = call_with_name
    delegate_to_attr = delegate_to_attr
    magic_kwargs = magic_kwargs


sys.modules[__name__] = Module
