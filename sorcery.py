import ast
import operator
import sys
from functools import lru_cache

from littleutils import file_to_string, only


def calling_stmt(context=1):
    frame = sys._getframe(context)
    filename = frame.f_code.co_filename
    lineno = frame.f_lineno
    return calling_stmt_at(filename, lineno)


@lru_cache()
def calling_stmt_at(filename, lineno):
    source = file_to_string(filename)
    tree = ast.parse(source)
    stmts = [node for node in ast.walk(tree)
             if isinstance(node, ast.stmt) and
             0 <= getattr(node, 'lineno', -1) <= lineno]
    return max(stmts, key=lambda stmt: stmt.lineno)


def assigned_names(context=1):
    stmt = calling_stmt(context=context + 2)
    return assigned_names_in_stmt(stmt)


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
    stmt = calling_stmt(context + 2)
    names = assigned_names_in_stmt(stmt)
    if isinstance(stmt, ast.Assign):
        return [getter(x, name) for name in names]
    else:  # for loop
        return ([getter(d, name) for name in names]
                for d in x)


def main():
    main.foo, bar = unpack_dict(
        dict(foo=7, bar=8)
    )
    print(main.foo, bar)

    for x, z in unpack_dict_get(
            [dict(x=1, y=2), dict(x=3, y=4)]):
        print(x, z)


main()
