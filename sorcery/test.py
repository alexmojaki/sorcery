from sorcery.spells import magic_kwargs, maybe
from sorcery import spells


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


def main():
    main.foo, bar = spells.unpack_keys(
        dict(foo=7, bar=8)
    )
    assert main.foo == 7
    assert bar == 8

    x = None
    for x, z in spells.unpack_keys(
            [dict(x=1, y=2), dict(z=3, y=4)], default=999):
        print(x, z)

    assert [(x, z) for x, z in
            spells.unpack_keys(
                [dict(x=1, y=2), dict(z=3, y=4)],
                default=999)] == [(1, 999), (999, 3)]

    x, y = map(int, spells.unpack_keys(dict(x='1', y='2')))
    spells.print_args(x + y)

    spells.print_args(1 + 2,
                      3 + 4)

    assert spells.dict_of(main, bar, x, a=1, y=2) == dict(main=main, bar=bar, x=x, a=1, y=2)

    lst = MyListWrapper([1, 2, 3])
    lst.append(4)
    lst.extend([1, 2])
    lst = (lst + [5]).copy()
    assert type(lst) is MyListWrapper
    assert lst == [1, 2, 3, 4, 1, 2, 5]

    @magic_kwargs
    def test_magic_kwargs(**kwargs):
        return list(kwargs.items())

    assert test_magic_kwargs(bar, x, a=3, b=5) == [('bar', bar), ('x', x), ('a', 3), ('b', 5)]

    n = None
    assert maybe(n) is None
    assert maybe(n).a.b.c()[4]().asd.asd()() is None
    assert maybe(0) is 0
    assert maybe({'a': 3})['a'] is 3
    assert maybe({'a': {'b': 3}})['a']['b'] is 3
    assert maybe({'a': {'b': 3}})['a']['b'] + 2 == 5
    assert maybe({'a': {'b': None}})['a']['b'] is None


main()
