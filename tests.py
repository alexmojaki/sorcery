import ast
import sqlite3
import sys
import traceback
import unittest
from io import StringIO
from time import sleep
from unittest import mock

from littleutils import SimpleNamespace, only

import sorcery as spells
from sorcery import unpack_keys, unpack_attrs, print_args, magic_kwargs, maybe, args_with_source, spell
from sorcery.spells import PYPY


class MyListWrapper(object):
    def __init__(self, lst):
        self.list = lst

    def _make_new_wrapper(self, method_name, *args, **kwargs):
        method = getattr(self.list, method_name)
        new_list = method(*args, **kwargs)
        return type(self)(new_list)

    append, extend, clear, __repr__, __str__, __eq__, __hash__, \
        __contains__, __len__, remove, insert, pop, index, count, \
        sort, __iter__, reverse, __iadd__ = spells.delegate_to_attr('list')

    copy, __add__, __radd__, __mul__, __rmul__ = spells.call_with_name(_make_new_wrapper)


class Foo(object):
    @magic_kwargs
    def bar(self, **kwargs):
        return set(kwargs.items()) | {self}


@magic_kwargs
def magic_only_kwarg(n, *, y):
    return n, y


class TestStuff(unittest.TestCase):
    def test_unpack_keys_basic(self):
        obj = SimpleNamespace(thing=SimpleNamespace())
        d = dict(foo=1, bar=3, spam=7, baz=8, x=9)
        out = {}
        foo, obj.thing.spam, obj.bar, out['baz'] = unpack_keys(d)
        self.assertEqual(foo, d['foo'])
        self.assertEqual(obj.bar, d['bar'])
        self.assertEqual(obj.thing.spam, d['spam'])
        self.assertEqual(out, {'baz': d['baz']})

    def test_unpack_keys_for_loop(self):
        results = []
        for x, y in unpack_keys([
            dict(x=1, y=2),
            dict(x=3, z=4),
            dict(a=5, y=6),
            dict(b=7, c=8),
        ], default=999):
            results.append((x, y))
        self.assertEqual(results, [
            (1, 2),
            (3, 999),
            (999, 6),
            (999, 999),
        ])

    def test_unpack_keys_list_comprehension(self):
        self.assertEqual(
            [(y, x) for x, y in unpack_keys([
                dict(x=1, y=2),
                dict(x=3, y=4),
            ])],
            [
                (2, 1),
                (4, 3),
            ])

    def test_unpack_keys_bigger_expression(self):
        x, y = map(int, unpack_keys(dict(x='1', y='2')))
        self.assertEqual(x, 1)
        self.assertEqual(y, 2)

    def test_unpack_keys_skip_single_assigned_name(self):
        x, y = [int(v) for v in unpack_keys(dict(x='1', y='2'))]
        self.assertEqual(x, 1)
        self.assertEqual(y, 2)

    def test_unpack_keys_extras(self):
        env = dict(DATABASE_USERNAME='me',
                   DATABASE_PASSWORD='secret')
        username, password = unpack_keys(env, prefix='DATABASE_', swapcase=True)
        self.assertEqual(username, 'me')
        self.assertEqual(password, 'secret')

    def test_unpack_attrs(self):
        obj = SimpleNamespace(aa='bv', bb='cc', cc='aa')
        cc, bb, aa = unpack_attrs(obj)
        self.assertEqual(aa, obj.aa)
        self.assertEqual(bb, obj.bb)
        self.assertEqual(cc, obj.cc)

        d, e = unpack_attrs(obj, default=9)
        assert d == e == 9

    def test_print_args(self):
        out = StringIO()
        x = 3
        y = 4
        print_args(x + y,
                   x * y,
                   x -
                   y, file=out)
        self.assertEqual('''\
x + y =
7

x * y =
12

x -
                   y =
-1

''', out.getvalue())

    def test_dict_of(self):
        a = 1
        obj = SimpleNamespace(b=2)
        self.assertEqual(spells.dict_of(
            a, obj.b,
            c=3, d=4
        ), dict(
            a=a, b=obj.b,
            c=3, d=4))

    def test_no_starargs_in_dict_of(self):
        args = [1, 2]
        with self.assertRaises(TypeError):
            spells.dict_of(*args)

    def test_delegation(self):
        lst = MyListWrapper([1, 2, 3])
        lst.append(4)
        lst.extend([1, 2])
        lst = (lst + [5]).copy()
        self.assertEqual(type(lst), MyListWrapper)
        self.assertEqual(lst, [1, 2, 3, 4, 1, 2, 5])

    def test_magic_kwargs(self):
        foo = Foo()
        x = 1
        y = 2
        w = 10
        self.assertEqual(foo.bar(x, y, z=3),
                         {('x', x), ('y', y), ('z', 3), foo})

        self.assertEqual(magic_only_kwarg(x, y), (x, y))

        @magic_kwargs
        def spam(n, **kwargs):
            return n, kwargs

        self.assertEqual(spam(x, y, z=5),
                         (x, dict(y=y, z=5)))

        @magic_kwargs
        def spam(n, m, **kwargs):
            return n, m, kwargs

        self.assertEqual(spam(x, w, y, z=5),
                         (x, w, dict(y=y, z=5)))

        with self.assertRaises(TypeError):
            @magic_kwargs
            def _(a=1):
                print(a)

        with self.assertRaises(TypeError):
            @magic_kwargs
            def _(*a):
                print(a)

    def test_maybe(self):
        if PYPY:
            with self.assertRaises(NotImplementedError):
                maybe(None)
            return

        n = None
        assert maybe(n) is None
        self.assertIsNone(maybe(n))
        assert maybe(n).a.b.c()[4]().asd.asd()() is None
        assert maybe(n)()()() is None
        assert maybe(0) == 0
        assert maybe({'a': 3})['a'] == 3
        assert maybe({'a': {'b': 3}})['a']['b'] == 3
        assert maybe({'a': {'b': 3}})['a']['b'] + 2 == 5
        assert maybe({'a': {'b': None}})['a']['b'] is None

    def test_select_from(self):
        conn = sqlite3.connect(':memory:')
        c = conn.cursor()
        c.execute('CREATE TABLE points (x INT, y INT)')
        c.execute("INSERT INTO points VALUES (5, 3), (8, 1)")
        conn.commit()

        assert [(3, 5), (1, 8)] == [(y, x) for y, x in spells.select_from('points')]
        y = 1
        x = spells.select_from('points', where=[y])
        assert (x, y) == (8, 1)

    def test_multiple_attr_calls(self):
        x = 3
        y = 5
        self.assertEqual([
            spells.dict_of(x),
            spells.dict_of(y),
        ], [dict(x=x), dict(y=y)])

        self.assertEqual([spells.dict_of(x), spells.dict_of(y)],
                         [dict(x=x), dict(y=y)])

    def test_no_assignment(self):
        with self.assertRaises(TypeError):
            unpack_keys(dict(x=1, y=2))

    def test_spell_repr(self):
        self.assertRegex(repr(spells.dict_of),
                         r'Spell\(<function dict_of at 0x.+>\)')

    def test_assigned_names(self):
        x, y = ['_' + s for s in spells.assigned_names()]
        self.assertEqual(x, '_x')
        self.assertEqual(y, '_y')

    # noinspection PyTrailingSemicolon
    def test_semicolons(self):
        # @formatter:off
        tester(1); tester(2); tester(3)
        tester(9
               ); tester(
            8); tester(
            99
        ); tester(33); tester([4,
                               5, 6, [
                               7]])
        # @formatter:on

    def test_args_with_source(self):
        self.assertEqual(args_with_source(1 + 2, 3 * 4),
                         [("1 + 2", 3), ("3 * 4", 12)])
        self.assertEqual(
            args_with_source(
                self.assertEqual(args_with_source(1 + 2), [("1 + 2", 3)])),
            [(
                'self.assertEqual(args_with_source(1 + 2), [("1 + 2", 3)])',
                None,
            )],
        )

    def test_switch(self):
        result = spells.switch(2, lambda: {
            1: 10,
            2: 20,
            1 / 0: 1 / 0
        })
        self.assertEqual(result, 20)

        result = spells.switch(2, lambda: {
            1: 10,
            {{5, 2, 1 / 0}}: 20,
            3: 1 / 0
        })
        self.assertEqual(result, 20)

        with self.assertRaises(KeyError):
            spells.switch(2, lambda: {
                1: 10,
                3: 30,
            })

        result = spells.switch(2, lambda: {
            1: 10,
            3: 30,
        }, default=-1)
        self.assertEqual(result, -1)

        with self.assertRaises(TypeError):
            spells.switch(2, {
                1: 10,
                2: 20,
            })

        with self.assertRaises(TypeError):
            spells.switch(2, lambda: [{
                1: 10,
                2: 20,
            }])

    def test_timeit_in_function(self):
        with self.assertRaises(ValueError):
            spells.timeit()

    def test_decorator(self):
        @empty_decorator
        @decorator_with_args(tester('123'), x=int())
        @tester(list(tuple([1, 2])), returns=empty_decorator)
        @tester(
            list(
                tuple(
                    [3, 4])),
            returns=empty_decorator)
        @empty_decorator
        @decorator_with_args(
            str(),
            x=int())
        @tester(list(tuple([5, 6])), returns=empty_decorator)
        @tester(list(tuple([7, 8])), returns=empty_decorator)
        @empty_decorator
        @decorator_with_args(tester('sdf'), x=tester('123234'))
        def foo():
            pass

    def test_list_comprehension(self):
        str([tester(int(x)) for x in tester([1]) for _ in tester([2]) for __ in [3]])
        str([[[tester(int(x)) for x in tester([1])] for _ in tester([2])] for __ in [3]])
        return str([(1, [
            (2, [
                tester(int(x)) for x in tester([1])])
            for _ in tester([2])])
                    for __ in [3]])

    def test_lambda(self):
        self.assertEqual((lambda x: (tester(x), tester(x)))(tester(3)), (3, 3))
        (lambda: (lambda: tester(1))())()
        self.assertEqual((lambda: [tester(x) for x in tester([1, 2])])(), [1, 2])

    def test_indirect_call(self):
        dict(x=tester)['x'](tester)(3)

    def test_compound_statements(self):
        with self.assertRaises(TypeError):
            try:
                for _ in tester([2]):
                    while tester(0):
                        pass
                    else:
                        tester(4)
                else:
                    tester(5)
                    raise ValueError
            except tester(ValueError):
                tester(9)
                raise TypeError
            finally:
                tester(10)

        # PyCharm getting confused somehow?
        # noinspection PyUnreachableCode
        str()

        with self.assertRaises(tester(Exception)):
            if tester(0):
                pass
            elif tester(0):
                pass
            elif tester(1 / 0):
                pass

    def test_generator(self):
        def gen():
            for x in [1, 2]:
                yield tester(x)

        gen2 = (tester(x) for x in tester([1, 2]))

        assert list(gen()) == list(gen2) == [1, 2]


@spell
def tester(frame_info, arg, returns=None):
    result = eval(
        compile(ast.Expression(only(frame_info.call.args)), '<>', 'eval'),
        frame_info.frame.f_globals,
        frame_info.frame.f_locals,
    )
    assert result == arg, (result, arg)
    if returns is None:
        return arg
    return returns


assert tester([1, 2, 3]) == [1, 2, 3]


def empty_decorator(f):
    return f


def decorator_with_args(*_, **__):
    return empty_decorator


class TestTimeit(unittest.TestCase):
    def patch(self, *args, **kwargs):
        patcher = mock.patch(*args, **kwargs)
        patcher.start()
        self.addCleanup(patcher.stop)

    def setUp(self):
        self.patch('sorcery.spells._raise', lambda e: e)
        self.patch('sys.stdout', StringIO())

    def assert_usual_output(self):
        self.assertRegex(
            sys.stdout.getvalue(),
            r"""
Number of trials: 1

Method 1: 1\.\d{3}
Method 2: 1\.\d{3}

Method 1: 1\.\d{3}
Method 2: 1\.\d{3}

Best times:
-----------
Method 1: 1\.\d{3}
Method 2: 1\.\d{3}
""".strip())

    def test_no_result(self):
        if spells.timeit(repeat=2):
            sleep(1)
        else:
            sleep(1.1)
        self.assert_usual_output()

    # noinspection PyUnusedLocal
    def test_matching_result(self):
        if spells.timeit(repeat=2):
            sleep(1)
            result = 3
        else:
            sleep(1.1)
            result = 3
        self.assert_usual_output()

    # noinspection PyUnusedLocal
    def test_not_matching_result(self):
        with self.assertRaises(AssertionError):
            if spells.timeit():
                result = 3
            else:
                result = 4

    def test_exception(self):
        try:
            if spells.timeit():
                print(1 / 0)
            else:
                pass
        except ZeroDivisionError:
            traceback.print_exc(file=sys.stdout)

        stdout = sys.stdout.getvalue()
        self.assertIn('<timeit-src>', stdout)
        self.assertIn('1 / 0', stdout)


if __name__ == '__main__':
    unittest.main()
