# sorcery

[![Build Status](https://travis-ci.org/alexmojaki/sorcery.svg?branch=master)](https://travis-ci.org/alexmojaki/sorcery) [![Coverage Status](https://coveralls.io/repos/github/alexmojaki/sorcery/badge.svg?branch=master)](https://coveralls.io/github/alexmojaki/sorcery?branch=master) [![Join the chat at https://gitter.im/python-sorcery/Lobby](https://badges.gitter.im/python-sorcery/Lobby.svg)](https://gitter.im/python-sorcery/Lobby?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge&utm_content=badge) [![Supports Python versions 3.5, 3.6, and 3.7](https://img.shields.io/pypi/pyversions/sorcery.svg)](https://pypi.python.org/pypi/sorcery)

This package lets you use and write callables called 'spells' that know where they're being called from and can use that information to do otherwise impossible things.

Note: previously spells had a complicated implementation that placed limitations on how they could be called. Now spells are just a thin wrapper around [`executing`](https://github.com/alexmojaki/executing) which is much better. You may be better off using `executing` directly depending on your use case. This repo is now mostly just a fun collection of things to do with it.

  * [Installation](#installation)
  * [Quick examples](#quick-examples)
     * [`assigned_names`](#assigned_names)
     * [`unpack_keys` and `unpack_attrs`](#unpack_keys-and-unpack_attrs)
     * [`dict_of`](#dict_of)
     * [`print_args`](#print_args)
     * [`call_with_name` and `delegate_to_attr`](#call_with_name-and-delegate_to_attr)
     * [`maybe`](#maybe)
     * [`timeit`](#timeit)
     * [`switch`](#switch)
     * [`select_from`](#select_from)
  * [How to write your own spells](#how-to-write-your-own-spells)
     * [Using other spells within spells](#using-other-spells-within-spells)
     * [Other helpers](#other-helpers)
  * [Should I actually use this library?](#should-i-actually-use-this-library)

## Installation

    pip install sorcery

## Quick examples

See the docstrings for more detail.

    from sorcery import (assigned_names, unpack_keys, unpack_attrs,
                         dict_of, print_args, call_with_name,
                         delegate_to_attr, maybe, select_from)

### `assigned_names`

Instead of:

    foo = func('foo')
    bar = func('bar')

write:

    foo, bar = [func(name) for name in assigned_names()]

Instead of:

    class Thing(Enum):
        foo = 'foo'
        bar = 'bar'

write:

    class Thing(Enum):
        foo, bar = assigned_names()

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

If you like this, I recommend the `pp` function in the [`snoop`](https://github.com/alexmojaki/snoop) library.

### `call_with_name` and `delegate_to_attr`

Sometimes you want to create many similar methods which differ only in a string argument which is equal to the name of the method. Given this class:

```python
class C:
    def generic(self, method_name, *args, **kwargs):
        ...
```

Inside the class definition, instead of:

```python
    def foo(self, x, y):
        return self.generic('foo', x, y)

    def bar(self, z):
        return self.generic('bar', z)
```

write:

```python
    foo, bar = call_with_name(generic)
```

For a specific common use case:

```python
class Wrapper:
    def __init__(self, thing):
        self.thing = thing

    def foo(self, x, y):
        return self.thing.foo(x, y)

    def bar(self, z):
        return self.thing.bar(z)
```

you can instead write:

```python
    foo, bar = delegate_to_attr('thing')
```

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

### `timeit`

Instead of

```python
import timeit

nums = [3, 1, 2]
setup = 'from __main__ import nums'

print(timeit.repeat('min(nums)', setup))
print(timeit.repeat('sorted(nums)[0]', setup))
```

write:

```python
import sorcery

nums = [3, 1, 2]

if sorcery.timeit():
    result = min(nums)
else:
    result = sorted(nums)[0]
```

### `switch`

Instead of:

```python
if val == 1:
    x = 1
elif val == 2 or val == bar():
    x = spam()
elif val == dangerous_function():
    x = spam() * 2
else:
    x = -1
```

write:

```python
x = switch(val, lambda: {
    1: 1,
    {{ 2, bar() }}: spam(),
    dangerous_function(): spam() * 2
}, default=-1)
```

This really will behave like the if/elif chain above. The dictionary is just
some nice syntax, but no dictionary is ever actually created. The keys
are evaluated only as needed, in order, and only the matching value is evaluated.

### `select_from`

Instead of:

```python
cursor.execute('''
    SELECT foo, bar
    FROM my_table
    WHERE spam = ?
      AND thing = ?
    ''', [spam, thing])

for foo, bar in cursor:
    ...
```

write:

```python
for foo, bar in select_from('my_table', where=[spam, thing]):
    ...
```

## How to write your own spells

Decorate a function with `@spell`. An instance of the class `FrameInfo` will be passed to the first argument of the function, while the other arguments will come from the call. For example:

```python
from sorcery import spell

@spell
def my_spell(frame_info, foo):
    ...
```

will be called as just `my_spell(foo)`.

The most important piece of information you are likely to use is `frame_info.call`. This is the `ast.Call` node where the spell is being called. [Here](https://greentreesnakes.readthedocs.io/en/latest/nodes.html) is some helpful documentation for navigating the AST. Every node also has a `parent` attribute added to it.

`frame_info.frame` is the execution frame in which the spell is being called - see the [inspect](https://docs.python.org/3/library/inspect.html) docs for what you can do with this.

Those are the essentials. See [the source](https://github.com/alexmojaki/sorcery/blob/master/sorcery/spells.py) of various spells for some examples, it's not that complicated.

### Using other spells within spells

Sometimes you want to reuse the magic of one spell in another spell. Simply calling the other spell won't do what you want - you want to tell the other spell to act as if it's being called from the place your own spell is called. For this, add insert `.at(frame_info)` between the spell you're using and its arguments.

Let's look at a concrete example. Here's the definition of the spell `args_with_source`:

```python
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
    ...
```

The magic of `args_with_source` is that it looks at its arguments wherever it's called and extracts their source code. Here is a simplified implementation of the `print_args` spell which uses that magic:

```python
@spell
def simple_print_args(frame_info, *args):
    for source, arg in args_with_source.at(frame_info)(*args):
        print(source, '=', arg)
```

Then when you call `simple_print_args(foo(), 1+2)`, the `Call` node of that expression will be passed down to `args_with_source.at(frame_info)` so that the source is extracted from the correct arguments. Simply writing `args_with_source(*args)` would be wrong, as that would give the source `"*args"`.

### Other helpers

That's all you really need to get started writing a spell, but here are pointers to some other stuff that might help. See the docstrings for details.

The module `sorcery.core` has these helper functions:

- `node_names(node: ast.AST) -> Tuple[str]`
- `node_name(node: ast.AST) -> str`
- `statement_containing_node(node: ast.AST) -> ast.stmt:`

`FrameInfo` has these methods:

- `assigned_names(...)`
- `get_source(self, node: ast.AST) -> str`

## Should I actually use this library?

If you're still getting the hang of Python, no. This will lead to confusion about what is normal and expected in Python and will hamper your learning.

In a serious business or production context, I wouldn't recommend most of the spells unless you're quite careful. Their unusual nature may confuse other readers of the code, and tying the behaviour of your code to things like the names of variables may not be good for readability and refactoring. There are some exceptions though:

- `call_with_name` and `delegate_to_attr`
- `assigned_names` for making `Enum`s.
- `print_args` when debugging

If you're writing code where performance and stability aren't critical, e.g. if it's for fun or you just want to get some code down as fast as possible and you can polish it later, then go for it.

The point of this library is not just to be used in actual code. It's a way to explore and think about API and language design, readability, and the limits of Python itself. It was fun to create and I hope others can have fun playing around with it. Come [have a chat](https://gitter.im/python-sorcery/Lobby) about what spells you think would be cool, what features you wish Python had, or what crazy projects you want to create.

If you're interested in this stuff, particularly creative uses of the Python AST, you may also be interested in:

- [executing](https://github.com/alexmojaki/executing) the backbone of this library
- [snoop](https://github.com/alexmojaki/snoop): a feature-rich and convenient debugging library which also uses `executing` as well as various other magic and tricks
- [birdseye](https://github.com/alexmojaki/birdseye): a debugger which records the value of every expression
- [MacroPy](https://github.com/lihaoyi/macropy): syntactic macros in Python by transforming the AST at import time
