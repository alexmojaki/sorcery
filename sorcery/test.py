import sqlite3

from sorcery import spells
from sorcery.spells import magic_kwargs, maybe


def main():
    bar = 3
    x = 9

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

    conn = sqlite3.connect(':memory:')
    c = conn.cursor()
    c.execute('CREATE TABLE points (x INT, y INT)')
    c.execute("INSERT INTO points VALUES (5, 3), (8, 1)")
    conn.commit()

    assert [(3, 5), (1, 8)] == [(y, x) for y, x in spells.select_from('points')]
    y = 1
    x = spells.select_from('points', where=[y])
    assert (x, y) == (8, 1)


main()
