import unittest

from sorcery import spells
from sorcery.spells import unpack_keys, unpack_attrs, print_args, magic_kwargs
from littleutils import SimpleNamespace
from io import StringIO


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


class TestStuff(unittest.TestCase):
    def test_unpack_keys_basic(self):
        obj = SimpleNamespace(thing=SimpleNamespace())
        d = dict(foo=1, bar=3, spam=7, x=9)
        foo, obj.thing.spam, obj.bar = unpack_keys(d)
        self.assertEqual(foo, d['foo'])
        self.assertEqual(obj.bar, d['bar'])
        self.assertEqual(obj.thing.spam, d['spam'])

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

    def test_unpack_attrs(self):
        obj = SimpleNamespace(aa='bv', bb='cc', cc='aa')
        cc, bb, aa = unpack_attrs(obj)
        self.assertEqual(aa, obj.aa)
        self.assertEqual(bb, obj.bb)
        self.assertEqual(cc, obj.cc)

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
        self.assertEqual(foo.bar(x, y, z=3),
                         {('x', x), ('y', y), ('z', 3), foo})


if __name__ == '__main__':
    unittest.main()
