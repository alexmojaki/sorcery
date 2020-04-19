import ast
import sys
from functools import lru_cache, partial
from typing import Tuple

from executing import only, Source


class FrameInfo(object):
    """
    Contains metadata about where a spell is being called.
    An instance of this is passed as the first argument to any spell.
    Users should not instantiate this class themselves.

    There are two essential attributes:

    - frame: the execution frame in which the spell is being called
    - call: the ast.Call node where the spell is being called
        See https://greentreesnakes.readthedocs.io/en/latest/nodes.html
        to learn how to navigate the AST
    """

    def __init__(self, executing):
        self.frame = executing.frame
        self.executing = executing
        self.call = executing.node

    def assigned_names(self, *,
                       allow_one: bool = False,
                       allow_loops: bool = False
                       ) -> Tuple[Tuple[str], ast.AST]:
        """
        Calls the function assigned_names for this instance's Call node.
        """
        return assigned_names(self.call,
                              allow_one=allow_one,
                              allow_loops=allow_loops)

    def get_source(self, node: ast.AST) -> str:
        """
        Returns a string containing the source code of an AST node in the
        same file as this call.
        """
        return self.executing.source.asttokens().get_text(node)


@lru_cache()
def statement_containing_node(node: ast.AST) -> ast.stmt:
    while not isinstance(node, ast.stmt):
        node = node.parent
    return node


@lru_cache()
def assigned_names(node, *,
                   allow_one: bool,
                   allow_loops: bool
                   ) -> Tuple[Tuple[str], ast.AST]:
    """
    Finds the names being assigned to in the nearest ancestor of
    the given node that assigns names and satisfies the given conditions.

    If allow_loops is false, this only considers assignment statements,
    e.g. `x, y = ...`. If it's true, then for loops and comprehensions are
    also considered.

    If allow_one is false, nodes which assign only one name are ignored.

    Returns:
    1. a tuple of strings containing the names of the nodes being assigned
    2. The AST node where the assignment happens
    """

    while hasattr(node, 'parent'):
        node = node.parent

        target = None

        if isinstance(node, ast.Assign):
            target = only(node.targets)
        elif isinstance(node, (ast.For, ast.comprehension)) and allow_loops:
            target = node.target

        if not target:
            continue

        names = node_names(target)
        if len(names) > 1 or allow_one:
            break
    else:
        raise TypeError('No assignment found')

    return names, node


def node_names(node: ast.AST) -> Tuple[str]:
    """
    Returns a tuple of strings containing the names of
    the nodes under the given node.

    The node must be a tuple or list literal, or a single named node.

    See the doc of the function node_name.
    """
    if isinstance(node, (ast.Tuple, ast.List)):
        names = tuple(node_name(x) for x in node.elts)
    else:
        names = (node_name(node),)
    return names


def node_name(node: ast.AST) -> str:
    """
    Returns the 'name' of a node, which is either:
     - the name of a variable
     - the name of an attribute
     - the contents of a string literal key, as in d['key']
    """
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return node.attr
    elif (isinstance(node, ast.Subscript) and
          isinstance(node.slice, ast.Index) and
          isinstance(node.slice.value, ast.Str)):
        return node.slice.value.s
    else:
        raise TypeError('Cannot extract name from %s' % node)


class Spell(object):
    """
    A Spell is a special callable that has information about where it's being
    called from.

    To create a spell, decorate a function with @spell.
    An instance of FrameInfo will be passed to the first argument of the function,
    while the other arguments will come from the call. For example:

        @spell
        def my_spell(frame_info, foo):
            ...

    will be called as just `my_spell(foo)`.
    """

    _excluded_codes = set()

    # Called when decorating a function
    def __init__(self, func):
        self.func = func

    # Called when a spell is accessed as an attribute
    # (see the descriptor protocol)
    def __get__(self, instance, owner):
        # Functions are descriptors, which allow methods to
        # automatically bind the self argument.
        # Here we have to manually invoke that.
        method = self.func.__get__(instance, owner)
        return Spell(method)

    def at(self, frame_info: FrameInfo):
        """
        Returns a callable that has frame_info already bound as the first argument
        of the spell, and will accept only the other arguments normally.

        Use this to use one spell inside another.
        """
        return partial(self.func, frame_info)

    # Called when the spell is called 'plainly', e.g. my_spell(foo),
    # i.e. just as a variable without being an attribute of anything.
    # Calls where the spell is an attribute go throuh __get__.
    def __call__(self, *args, **kwargs):
        frame = sys._getframe(1)

        while frame.f_code in self._excluded_codes:
            frame = frame.f_back

        executing = Source.executing(frame)
        assert executing.node, "Failed to find call node"
        return self.at(FrameInfo(executing))(*args, **kwargs)

    def __repr__(self):
        return '%s(%r)' % (
            self.__class__.__name__,
            self.func
        )


spell = Spell


def no_spells(func):
    """
    Decorate a function with this to indicate that no spells are used
    directly in this function, but the function may be used to
    access a spell dynamically. Spells looking for where they are being
    called from will skip the decorated function and look at the enclosing
    frame instead.

    For example, suppose you have a class with a method that is a spell,
    e.g.:

        class A:
            @ magic_kwargs  # makes foo a spell
            def foo(self, **kwargs):
                pass

    And another class that wraps the first:

        class B:
            def __init__(self):
                self.a = A()

    And you want users to call foo without going through A, you could write:

            @no_spells
            def foo(self, **kwargs):
                self.a.foo(**kwargs)

    Note that the method B.foo must have the same name (foo) as the spell A.foo.

    Or, if you wanted to delegate all unknown attributes to `self.a`, you could write:

            @no_spells
            def __getattr__(self, item):
                return getattr(self.a, item)

    In either case `B().foo(...)` will work as expected.
    """

    Spell._excluded_codes.add(func.__code__)
    return func
