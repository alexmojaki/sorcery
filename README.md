# sorcery

This package lets you write 'functions' that know where they're being called from and can use that information to do otherwise impossible things. Here are some quick examples (see the docstrings for more detail):

    from sorcery import assigned_names, unpack_keys, unpack_attrs, dict_of, print_args, call_with_name, delegate_to_attr, maybe, select_from

### `assigned_names`

Instead of:

    foo = func('foo')
    bar = func('bar')

write:

    foo, bar = [func(name) for name in assigned_names()]

### `unpack_keys` and `unpack_attrs`

Instead of:

    foo = d['foo']
    bar = d['bar']

write:

    foo, bar = unpack_keys(d)

Similarly, instead of:

    foo = x.foo
    bar = x.bar

write:

    foo, bar = unpack_attrs(x)

### `dict_of`

Instead of:

    dict(foo=foo, bar=bar, spam=thing())

write:

    dict_of(foo, bar, spam=thing())

(see also: `magic_kwargs`)

### `print_args`

For easy debugging, instead of:

    print("foo =", foo)
    print("bar() =", bar())

write:

    print_args(foo, bar())

To write your own version of this (e.g. if you want to add colour), use `args_with_source`.

The packages [q](https://github.com/zestyping/q) and [https://github.com/gruns/icecream](https://github.com/gruns/icecream) have similar functionality.

### `call_with_name` and `delegate_to_attr`

Sometimes you want to create many similar methods which differ only in a string argument which is equal to the name of the method. Given this class:

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

For a specific common use case:

    class Wrapper:
        def __init__(self, thing):
            self.thing = thing

        def foo(self, x, y):
            return self.thing.foo(x, y)

        def bar(self, z):
            return self.thing.bar(z)

you can instead write:

        foo, bar = delegate_to_attr('thing')

For a more concrete example, here is a class that wraps a list and has all the usual list methods while ensuring that any methods which usually create a new list actually create a new wrapper:

```python
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
```

Of course, there are less magical DRY ways to accomplish this (e.g. looping over some strings and using `setattr`), but they will not tell your IDE/linter what methods `MyListWrapper` has or doesn't have.

### `maybe`

While we wait for the `?.` operator from [PEP 505](https://www.python.org/dev/peps/pep-0505/), here's an alternative. Instead of:

    None if foo is None else foo.bar()

write:

    maybe(foo).bar()

If you want a slightly less magical version, consider [pymaybe](https://github.com/ekampf/pymaybe).

### `select_from`

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
