import ast
import operator
from pprint import pprint
from itertools import chain
import wrapt
from littleutils import only

from sorcery.core import spell, wrap_module, node_names, node_name

_NO_DEFAULT = object()


@spell
def unpack_keys(frame_info, x, default=_NO_DEFAULT, prefix=None, swapcase=False):
    """
    Instead of:

        foo = d['foo']
        bar = d['bar']

    write:

        foo, bar = unpack_keys(d)

    Instead of:

        foo = d.get('foo', 0)
        bar = d.get('bar', 0)

    write:

        foo, bar = unpack_keys(d, default=0)

    Instead of:

        foo = d['data_foo']
        bar = d['data_bar']

    write:

        foo, bar = unpack_keys(d, prefix='data_')

    Instead of:

        foo = d['FOO']
        bar = d['BAR']

    write:

        foo, bar = unpack_keys(d, swapcase=True)

    and similarly, instead of:

        FOO = d['foo']
        BAR = d['bar']

    write:

        FOO, BAR = unpack_keys(d, swapcase=True)
    """

    if default is _NO_DEFAULT:
        getter = operator.getitem
    else:
        # Essentially dict.get, without relying on that method existing
        def getter(d, name):
            try:
                return d[name]
            except KeyError:
                return default

    return _unpack(frame_info, x, getter, prefix, swapcase)


@spell
def unpack_attrs(frame_info, x, default=_NO_DEFAULT, prefix=None, swapcase=False):
    if default is _NO_DEFAULT:
        getter = getattr
    else:
        def getter(d, name):
            return getattr(d, name, default)

    return _unpack(frame_info, x, getter, prefix, swapcase)


def _unpack(frame_info, x, getter, prefix, swapcase):
    names, node = frame_info.assigned_names

    def fix_name(n):
        if swapcase:
            n = n.swapcase()
        if prefix:
            n = prefix + n
        return n

    if isinstance(node, ast.Assign):
        return [getter(x, fix_name(name)) for name in names]
    else:  # for loop
        return ([getter(d, fix_name(name)) for name in names]
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
        node_name(arg): value
        for arg, value in zip(frame_info.call.args, args)
    }
    result.update(kwargs)
    return result


@spell
def print_args(frame_info, *args, file=None):
    for source, arg in args_with_source[frame_info](args):
        print(source + ' =', file=file)
        pprint(arg, stream=file)
        print(file=file)
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


class _Nothing(object):
    def __init__(self, count):
        self.__count = count

    def __getattribute__(self, item):
        if item == '_Nothing__count':
            return object.__getattribute__(self, item)
        return _Nothing.__op(self)

    def __op(self, *_args, **_kwargs):
        self.__count -= 1
        if self.__count == 0:
            return None

        return self

    __getitem__ = __call__ = __op


@spell
def maybe(frame_info, x):
    node = frame_info.call
    count = 0
    while True:
        parent = node.parent
        if not (isinstance(parent, ast.Attribute) or
                isinstance(parent, ast.Call) and parent.func is node or
                isinstance(parent, ast.Subscript) and parent.value is node):
            break
        count += 1
        node = parent

    if count == 0 or x is not None:
        return x

    return _Nothing(count)


@spell
def select_from(frame_info, sql, params=(), cursor=None, where=None):
    if cursor is None:
        frame = frame_info.frame
        cursor = only(c for c in chain(frame.f_locals.values(),
                                       frame.f_globals.values())
                      if 'cursor' in str(type(c).__mro__).lower() and
                      callable(getattr(c, 'execute', None)))
    names, node = frame_info.assigned_names
    sql = 'SELECT %s FROM %s' % (', '.join(names), sql)

    if where:
        where_arg = only(kw.value for kw in frame_info.call.keywords
                         if kw.arg == 'where')
        where_names = node_names(where_arg)
        assert len(where_names) == len(where)
        sql += ' WHERE ' + ' AND '.join('%s = ?' % name for name in where_names)
        params = where

    cursor.execute(sql, params)

    def unpack(row):
        if len(row) == 1:
            return row[0]
        else:
            return row

    if isinstance(node, ast.Assign):
        return unpack(cursor.fetchone())
    else:
        def vals():
            for row in cursor:
                yield unpack(row)

        return vals()


def magic_kwargs(func):
    @wrapt.decorator
    def wrapper(wrapped, _instance, args, kwargs):
        # if instance is not None:
        #     raise TypeError('magic_kwargs can only be applied to free functions, not methods')
        full_kwargs = dict_of[args[0]](*args[1:], **kwargs)
        return wrapped(**full_kwargs)

    return spell(wrapper(func))


wrap_module(__name__, globals())
