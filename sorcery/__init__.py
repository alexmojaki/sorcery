import ast
import operator
import sys
from pprint import pprint

from asttokens import ASTTokens
from littleutils import file_to_string, only
from cached_property import cached_property

try:
    from functools import lru_cache
except ImportError:
    from backports.functools_lru_cache import lru_cache

__version__ = '0.0.1'


@lru_cache()
class FileInfo(object):
    def __init__(self, path):
        self.source = file_to_string(path)
        self.tree = ast.parse(self.source, filename=path)
        self.path = path

    @cached_property
    def tokens(self):
        return ASTTokens(self.source, tree=self.tree, filename=self.path)

    @lru_cache()
    def stmt_at_line(self, lineno):
        stmts = [node for node in ast.walk(self.tree)
                 if isinstance(node, ast.stmt) and
                 0 <= getattr(node, 'lineno', -1) <= lineno]
        return max(stmts, key=lambda stmt: stmt.lineno)


class FrameInfo(object):

    def __init__(self, context):
        self.inner_frame = sys._getframe(context)
        self.frame = self.inner_frame.f_back

    @property
    def stmt(self):
        return self.file_info.stmt_at_line(self.frame.f_lineno)

    @property
    def assigned_names(self):
        return assigned_names_in_stmt(self.stmt)

    @property
    def potential_calls(self):
        code_name = self.inner_frame.f_code.co_name
        return get_potential_calls_in_stmt(self.stmt, code_name)

    @property
    def file_info(self):
        return FileInfo(self.frame.f_code.co_filename)


@lru_cache()
def assigned_names_in_stmt(stmt):
    if isinstance(stmt, ast.Assign):
        target = only(stmt.targets)
    elif isinstance(stmt, ast.For):
        target = stmt.target
    else:
        raise TypeError('Assignment or for loop required, found %r' % stmt)
    if isinstance(target, (ast.Tuple, ast.List)):
        return tuple(_target_name(x) for x in target.elts)
    else:
        return _target_name(target),


def _target_name(target):
    if isinstance(target, ast.Name):
        return target.id
    elif isinstance(target, ast.Attribute):
        return target.attr
    else:
        raise TypeError('Cannot extract name from %s' % target)


def unpack_dict(x, context=1):
    return _unpack(x, context, operator.getitem)


def unpack_dict_get(x, default=None, context=1):
    return _unpack(x, context, lambda d, name: d.get(name, default))


def unpack_attrs(x, context=1):
    return _unpack(x, context, getattr)


def _unpack(x, context, getter):
    stmt = FrameInfo(context + 1).stmt
    names = assigned_names_in_stmt(stmt)
    if isinstance(stmt, ast.Assign):
        return [getter(x, name) for name in names]
    else:  # for loop
        return ([getter(d, name) for name in names]
                for d in x)


@lru_cache()
def get_potential_calls_in_stmt(stmt, code_name):
    return [node for node in ast.walk(stmt)
            if isinstance(node, ast.Call) and
            isinstance(node.func, ast.Name) and
            node.func.id == code_name]


def args_with_source(args, context=2):
    frame_info = FrameInfo(context)
    call = only(frame_info.potential_calls)
    tokens = frame_info.file_info.tokens
    return [
        (tokens.get_text(arg), value)
        for arg, value in zip(call.args, args)
    ]


def dict_of(*args, **kwargs):
    frame_info = FrameInfo(1)
    call = only(frame_info.potential_calls)
    result = {
        arg.id: value
        for arg, value in zip(call.args, args)
    }
    result.update(kwargs)
    return result


def print_args(*args):
    for source, arg in args_with_source(args):
        print(source + ' =')
        pprint(arg)
        print()
    return args and args[0]


def call_with_name(func):
    def make_func(name):
        return lambda self, *args, **kwargs: func(self, name, *args, **kwargs)

    return [
        make_func(name)
        for name in FrameInfo(1).assigned_names
    ]


def delegate_to_attr(attr_name):
    def make_func(name):
        return property(lambda self: getattr(getattr(self, attr_name), name))

    return [
        make_func(name)
        for name in FrameInfo(1).assigned_names
    ]


class MyListWrapper(object):
    def __init__(self, lst):
        self.list = lst

    def _make_new_wrapper(self, method_name, *args, **kwargs):
        method = getattr(self.list, method_name)
        new_list = method(*args, **kwargs)
        return type(self)(new_list)

    append, extend, clear, __repr__, __str__, __eq__, __hash__, \
    __contains__, __len__, remove, insert, pop, index, count, \
    sort, __iter__, reverse, __iadd__ = delegate_to_attr('list')

    copy, __add__, __radd__, __mul__, __rmul__ = call_with_name(_make_new_wrapper)


def main():
    main.foo, bar = unpack_dict(
        dict(foo=7, bar=8)
    )
    print(main.foo, bar)

    x = None
    for x, z in unpack_dict_get(
            [dict(x=1, y=2), dict(x=3, y=4)]):
        print(x, z)

    print_args(1 + 2,
               3 + 4)
    print(dict_of(main, bar, x, a=1, y=2))

    lst = MyListWrapper([1, 2, 3])
    lst.append(4)
    lst.extend([1, 2])
    print(type((lst + [5]).copy()))


main()
