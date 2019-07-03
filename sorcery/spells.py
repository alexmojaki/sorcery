from __future__ import generator_stop

import ast
import operator
import timeit as real_timeit
import unittest
from functools import lru_cache
from inspect import signature
from io import StringIO
from itertools import chain
from pprint import pprint
from textwrap import dedent

import wrapt
from littleutils import only
from sorcery.core import spell, node_names, node_name

_NO_DEFAULT = object()


@spell
def assigned_names(frame_info):
    """
    Instead of:

        foo = func('foo')
        bar = func('bar')

    write:

        foo, bar = map(func, assigned_names())

    or:

        foo, bar = [func(name) for name in assigned_names()]

    Instead of:

        class Thing(Enum):
            foo = 'foo'
            bar = 'bar'

    write:

        class Thing(Enum):
            foo, bar = assigned_names()

    More generally, this function returns a tuple of strings representing the names being assigned to.

    The result can be assigned to any combination of either:

      - plain variables,
      - attributes, or
      - subscripts (square bracket access) with string literal keys

    So the following:

        spam, x.foo, y['bar'] = assigned_names()

    is equivalent to:

        spam = 'spam'
        x.foo = 'foo'
        y['bar'] = 'bar'

    Any expression is allowed to the left of the attribute/subscript.

    Only simple tuple unpacking is allowed:

      - no nesting, e.g.  (a, b), c = ...
      - no stars, e.g.    a, *b = ...
      - no chains, e.g.   a, b = c = ...
      - no assignment to a single name without unpacking, e.g.  a = ...
    """
    return frame_info.assigned_names()[0]


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

    Note that swapcase is not applied to the prefix, so for example you should write:

        env = dict(DATABASE_USERNAME='me',
                   DATABASE_PASSWORD='secret')
        username, password = unpack_keys(env, prefix='DATABASE_', swapcase=True)

    The rules of the assigned_names spell apply.

    This can be seamlessly used in for loops, even inside comprehensions, e.g.

        for foo, bar in unpack_keys(list_of_dicts):
            ...

    If there are multiple assignment targets in the statement, e.g. if you have
    a nested list comprehension, the target nearest to the function call will
    determine the keys. For example, the keys 'foo' and 'bar' will be extracted in:

        [[foo + bar + y for foo, bar in unpack_keys(x)]
         for x, y in z]

    Like assigned_names, the unpack call can be part of a bigger expression,
    and the assignment will still be found. So for example instead of:

        foo = int(d['foo'])
        bar = int(d['bar'])

    you can write:

        foo, bar = map(int, unpack_keys(d))

    or:

        foo, bar = [int(v) for v in unpack_keys(d)]

    The second version works because the spell looks for multiple names being assigned to,
    so it doesn't just unpack 'v'.

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
    """
    This is similar to unpack_keys, but for attributes.

    Instead of:

        foo = x.foo
        bar = x.bar

    write:

        foo, bar = unpack_attrs(x)
    """

    if default is _NO_DEFAULT:
        getter = getattr
    else:
        def getter(d, name):
            return getattr(d, name, default)

    return _unpack(frame_info, x, getter, prefix, swapcase)


def _unpack(frame_info, x, getter, prefix, swapcase):
    names, node = frame_info.assigned_names(allow_loops=True)

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
def args_with_source(frame_info, *args):
    """
    Returns a list of pairs of:
        - the source code of the argument
        - the value of the argument
    for each argument.

    For example:

        args_with_source(foo(), 1+2)

    is the same as:

        [
            ("foo()", foo()),
            ("1+2", 3)
        ]
    """
    return [
        (frame_info.get_source(arg), value)
        for arg, value in zip(frame_info.call.args, args)
    ]


@spell
def dict_of(frame_info, *args, **kwargs):
    """
    Instead of:

        {'foo': foo, 'bar': bar, 'spam': thing()}

    or:

        dict(foo=foo, bar=bar, spam=thing())

    write:

        dict_of(foo, bar, spam=thing())

    In other words, returns a dictionary with an item for each argument,
    where positional arguments use their names as keys,
    and keyword arguments do the same as in the usual dict constructor.

    The positional arguments can be any of:

      - plain variables,
      - attributes, or
      - subscripts (square bracket access) with string literal keys

    So the following:

        dict_of(spam, x.foo, y['bar'])

    is equivalent to:

        dict(spam=spam, foo=x.foo, bar=y['bar'])

    *args are not allowed.

    To give your own functions the ability to turn positional argments into
    keyword arguments, use the decorator magic_kwargs.

    """

    result = {
        node_name(arg): value
        for arg, value in zip(frame_info.call.args[-len(args):], args)
    }
    result.update(kwargs)
    return result


@spell
def print_args(frame_info, *args, file=None):
    """
    For each argument, prints the source code of that argument
    and its value. Returns the first argument.
    """
    for source, arg in args_with_source.at(frame_info)(*args):
        print(source + ' =', file=file)
        pprint(arg, stream=file)
        print(file=file)
    return args and args[0]


@spell
def call_with_name(frame_info, func):
    """
    Given:
    
        class C:
            def generic(self, method_name, *args, **kwargs):
                ...
                
    Inside the class definition, instead of:

            def foo(self, x, y):
                return self.generic('foo', x, y)
            
            def bar(self, z):
                return self.generic('bar', z)
    
    write:
    
            foo, bar = call_with_name(generic)

    This only works for methods inside classes, not free functions.
    """
    def make_func(name):
        return lambda self, *args, **kwargs: func(self, name, *args, **kwargs)

    return [
        make_func(name)
        for name in frame_info.assigned_names()[0]
    ]


@spell
def delegate_to_attr(frame_info, attr_name):
    """
    This is a special case of the use case fulfilled by call_with_name.
    
    Given:
    
        class Wrapper:
            def __init__(self, thing):
                self.thing = thing
            
    Inside the class definition, instead of:
    
            def foo(self, x, y):
                return self.thing.foo(x, y)
            
            def bar(self, z):
                return self.thing.bar(z)

    Write:
    
            foo, bar = delegate_to_attr('thing')

    Specifically, this will make:

        Wrapper().foo

    equivalent to:

        Wrapper().thing.foo
    """
    def make_func(name):
        return property(lambda self: getattr(getattr(self, attr_name), name))

    return [
        make_func(name)
        for name in frame_info.assigned_names()[0]
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
    """
    Instead of:

        None if foo is None else foo.bar()

    write:

        maybe(foo).bar()

    Specifically, if foo is not None, then maybe(foo) is just foo.

    If foo is None, then any sequence of attributes, subscripts, or
    calls immediately to the right of maybe(foo) is ignored, and
    the final result is None. So maybe(foo)[0].x.y.bar() is None,
    while func(maybe(foo)[0].x.y.bar()) is func(None) because enclosing
    expressions are not affected.
    """
    if x is not None:
        return x

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

    if count == 0:
        return x

    return _Nothing(count)


@spell
def select_from(frame_info, sql, params=(), cursor=None, where=None):
    """
    Instead of:

        cursor.execute('''
            SELECT foo, bar
            FROM my_table
            WHERE spam = ?
              AND thing = ?
            ''', [spam, thing])

        for foo, bar in cursor:
            ...

    write:

        for foo, bar in select_from('my_table', where=[spam, thing]):
            ...

    Specifically:
        - the assigned names (similar to the assigned_names and unpack_keys spells)
            are placed in the SELECT clause
        - the first argument (usually just a table name but can be any SQL)
            goes after the FROM
        - if the where argument is supplied, it must be a list or tuple literal of values
            which are supplied as query parameters and whose names are used in a
            WHERE clause using the = and AND operators.
            If you use this argument, don't put a WHERE clause in the sql argument and
            don't supply params
        - a cursor object is automatically pulled from the calling frame, but if this
            doesn't work you can supply one with the cursor keyword argument
        - the params argument can be supplied for more custom cases than the where
            argument provides.
        - if this is used in a loop or list comprehension, all rows in the result
            will be iterated over.
            If it is used in an assignment statement, one row will be returned.
        - If there are multiple names being assigned (i.e. multiple columns being selected)
            then the row will be returned and thus unpacked. If there is only one name,
            it will automatically be unpacked so you don't have to add [0].

    This spell is much more a fun rough idea than the others. It is expected that there
    are many use cases it will not fit into nicely.
    """
    if cursor is None:
        frame = frame_info.frame
        cursor = only(c for c in chain(frame.f_locals.values(),
                                       frame.f_globals.values())
                      if 'cursor' in str(type(c).__mro__).lower() and
                      callable(getattr(c, 'execute', None)))
    names, node = frame_info.assigned_names(allow_one=True, allow_loops=True)
    sql = 'SELECT %s FROM %s' % (', '.join(names), sql)

    if where:
        where_arg = only(kw.value for kw in frame_info.call.keywords
                         if kw.arg == 'where')
        where_names = node_names(where_arg)
        assert len(where_names) == len(where)
        sql += ' WHERE ' + ' AND '.join('%s = ?' % name for name in where_names)
        assert params == ()
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
    """
    Applying this decorator allows a function to interpret positional
    arguments as keyword arguments, using the name of the positional argument
    as the keyword. For example, given:

        @magic_kwargs
        def func(*, foo, bar, spam):

    or

        @magic_kwargs
        def func(**kwargs):

    then instead of:

        func(foo=foo, bar=bar, spam=thing)

    you can just write:

        func(foo, bar, spam=thing)

    Without the @magic_kwargs, the closest magical alternative would be:

        func(**dict_of(foo, bar, spam=thing))

    The function is not allowed to have optional positional parameters, e.g.
    `def func(x=1)`, or *args.
    """

    args_count = 0
    for param in signature(func).parameters.values():
        if (param.kind == param.VAR_POSITIONAL or
                param.kind == param.POSITIONAL_OR_KEYWORD and
                param.default != param.empty):
            raise TypeError(
                'The type of the parameter %s is not allowed with @magic_kwargs'
                % param.name)
        if param.kind == param.POSITIONAL_OR_KEYWORD:
            args_count += 1

    @wrapt.decorator
    def wrapper(wrapped, instance, args, kwargs):
        frame_info, *args = args
        count = args_count - (instance is not None)  # account for self argument
        normal_args = args[:count]
        magic_args = args[count:]
        full_kwargs = dict_of.at(frame_info)(*magic_args, **kwargs)
        return wrapped(*normal_args, **full_kwargs)

    return spell(wrapper(func))


@spell
def switch(frame_info, val, _cases, *, default=_NO_DEFAULT):
    """
    Instead of:

        if val == 1:
            x = 1
        elif val == 2 or val == bar():
            x = spam()
        elif val == dangerous_function():
            x = spam() * 2
        else:
            x = -1

    write:

        x = switch(val, lambda: {
            1: 1,
            {{ 2, bar() }}: spam(),
            dangerous_function(): spam() * 2
        }, default=-1)

    This really will behave like the if/elif chain above. The dictionary is just
    some nice syntax, but no dictionary is ever actually created. The keys
    are evaluated only as needed, in order, and only the matching value is evaluated.
    The keys are not hashed, only compared for equality, so non-hashable keys like lists
    are allowed.

    If the default is not specified and no matching value is found, a KeyError is raised.

    Note that `if val == 2 or val == bar()` is translated to `{{ 2, bar() }}`.
    This is to allow emulating multiple case clauses for the same block as in
    the switch construct in other languages. The double braces {{}} create a value
    that's impossible to evaluate normally (a set containing a set) so that it's clear
    we don't simply want to check `val == {{ 2, bar() }}`, whereas `{2, bar()}` would be
    evaluated and checked normally.
    As always, the contents are lazily evaluated and compared in order.

    The keys and values are evaluated with the compiler statement
    `from __future__ import generator_stop` in effect (which you should really be
    considering using anyway if you're using Python < 3.7).

    """

    frame = frame_info.frame
    switcher = _switcher(frame_info.call.args[1], frame.f_code)

    def ev(k):
        return eval(k, frame.f_globals, frame.f_locals)

    def check(k):
        return ev(k) == val

    for key_code, value_code in switcher:
        if isinstance(key_code, tuple):
            test = any(map(check, key_code))
        else:
            test = check(key_code)
        if test:
            return ev(value_code)

    if default is _NO_DEFAULT:
        raise KeyError(val)
    else:
        return default


@lru_cache()
def _switcher(cases, f_code):
    if not (isinstance(cases, ast.Lambda) and
            isinstance(cases.body, ast.Dict)):
        raise TypeError('The second argument to switch must be a lambda with no arguments '
                        'that returns a dictionary literal')

    def comp(node):
        return compile(ast.Expression(node),
                       filename=f_code.co_filename,
                       mode='eval')

    result = []
    for key, value in zip(cases.body.keys,
                          cases.body.values):

        if (isinstance(key, ast.Set) and
                isinstance(key.elts[0], ast.Set)):
            key_code = tuple(comp(k) for k in key.elts[0].elts)
        else:
            key_code = comp(key)

        result.append((key_code, comp(value)))
    return result


def _raise(e):
    # for tests
    raise e


class TimerWithExc(real_timeit.Timer):
    def timeit(self, *args, **kwargs):
        try:
            return super().timeit(*args, **kwargs)
        except:
            # Sets up linecache for future tracebacks
            self.print_exc(StringIO())
            raise


@spell
def timeit(frame_info, repeat=5):
    """
    This function is for writing quick scripts for comparing the speeds
    of two snippets of code that do the same thing. It's a nicer interface
    to the standard timeit module that doesn't require putting your code in strings, so you can
    use your IDE features, while still using the standard timeit for accuracy.
    
    Instead of
    
        import timeit
    
        nums = [3, 1, 2]
        setup = 'from __main__ import nums'
        
        print(timeit.repeat('min(nums)', setup))
        print(timeit.repeat('sorted(nums)[0]', setup))
    
    write:
    
        import sorcery
    
        nums = [3, 1, 2]
        
        if sorcery.timeit():
            result = min(nums)
        else:
            result = sorted(nums)[0]
            
    The if statement is just syntax for denoting the two blocks of code
    being tested. Some other nice features of this function over the standard
    timeit:
    
    - Automatically determines a high enough 'number' argument.
    - Asserts that any variable named 'result' is equal in both snippets,
      for correctness testing. The variable should be present in both or
      neither snippets.
    - Nice formatting of results for easy comparison, including best times
    - Source lines shown in tracebacks
    
    The spell must be called at the top level of a module, not inside
    another function definition.
    """
    
    globs = frame_info.frame.f_globals
    if globs is not frame_info.frame.f_locals:
        _raise(ValueError('Must execute in global scope'))

    setup = 'from %s import %s\n' % (
        globs['__name__'],
        ', '.join(globs.keys()),
    )
    if_stmt = frame_info.call.parent
    stmts = [
        dedent('\n'.join(map(frame_info.get_source, lines)))
        for lines in [if_stmt.body, if_stmt.orelse]
    ]

    timers = [
        TimerWithExc(stmt, setup)
        for stmt in stmts
    ]

    # Check for exceptions
    for timer in timers:
        timer.timeit(1)

    # Compare results
    def get_result(stmt):
        ns = {}
        exec(setup + stmt, ns)
        return ns.get('result')

    unittest.TestCase('__init__').assertEqual(
        *map(get_result, stmts),
        '\n=====\nThe two methods yielded different results!'
    )

    # determine number so that 1 <= total time < 3
    number = 1
    for i in range(22):
        number = 3 ** i
        if timers[0].timeit(number) >= 1:
            break

    print('Number of trials:', number)
    print()

    def print_time(idx, el):
        print('Method {}: {:.3f}'.format(
            idx + 1, el))

    times = [[] for _ in timers]
    for _ in range(repeat):
        for i, timer in enumerate(timers):
            elapsed = timer.timeit(number)
            print_time(i, elapsed)
            times[i].append(elapsed)
        print()

    print('Best times:')
    print('-----------')
    for i, elapsed_list in enumerate(times):
        print_time(i, min(elapsed_list))
    