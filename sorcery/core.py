import ast
import sys
import tokenize
from collections import defaultdict
from functools import lru_cache, partial
from typing import Optional, List, Tuple

import wrapt
from asttokens import ASTTokens
from littleutils import only


class FileInfo(object):
    """
    Contains metadata about a python source file:

        - path: path to the file
        - source: text contents of the file
        - tree: AST parsed from the source
        - asttokens(): ASTTokens object for getting the source of specific AST nodes
        - nodes_by_lines: dictionary from line numbers
            to a list of AST nodes at that line

    Each node in the AST has an extra attribute 'parent'.

    Users should not need to create instances of this class themselves.
    This class should not be instantiated directly, rather use file_info for caching.
    """

    def __init__(self, path):
        with tokenize.open(path) as f:
            self.source = f.read()
        self.tree = ast.parse(self.source, filename=path)
        self.nodes_by_line = defaultdict(list)
        for node in ast.walk(self.tree):
            for child in ast.iter_child_nodes(node):
                child.parent = node
            if hasattr(node, 'lineno'):
                self.nodes_by_line[node.lineno].append(node)
        self.path = path

    @staticmethod
    def for_frame(frame) -> 'FileInfo':
        return file_info(frame.f_code.co_filename)

    @lru_cache()
    def asttokens(self) -> ASTTokens:
        """
        Returns an ASTTokens object for getting the source of specific AST nodes.

        See http://asttokens.readthedocs.io/en/latest/api-index.html
        """
        return ASTTokens(self.source, tree=self.tree, filename=self.path)

    @lru_cache()
    def _attr_call_at(self, line: int, name: str) -> Optional[ast.Call]:
        """
        Searches for a Call at the given line where the callable is
        an attribute with the given name, i.e.

            obj.<name>(...)

        This is mainly to allow:

            import sorcery

            sorcery.some_spell(...)

        Returns None if there is no such call. Raises an error if there
        are several on the same line.
        """
        options = [node for node in self.nodes_by_line[line]
                   if isinstance(node, ast.Call) and
                   isinstance(node.func, ast.Attribute) and
                   node.func.attr == name]
        if not options:
            return None

        if len(options) == 1:
            return options[0]

        raise ValueError('Found %s possible calls to %s' % (len(options), name))

    @lru_cache()
    def _plain_calls_in_stmt_at_line(self, lineno: int) -> List[ast.Call]:
        """
        Returns a list of the Call nodes in the statement containing this line
        which are 'plain', i.e. the callable is just a variable name, not an
        attribute or some other expression.

        Note that this can return Call nodes that aren't at the given line,
        as long as they are in the statement that contains the line.

        Because a statement is inferred from a line number, there must be no
        semicolons separating statements on this line.
        """
        stmt = only({
            statement_containing_node(node)
            for node in
            self.nodes_by_line[lineno]})  # finds only statement at line - no semicolons allowed
        return [node for node in ast.walk(stmt)
                if isinstance(node, ast.Call) and
                isinstance(node.func, ast.Name)]

    def _plain_call_at(self, frame, val) -> ast.Call:
        """
        Returns the Call node currently being evaluated in this frame where
        the callable is just a variable name, not an attribute or some other expression,
        and that name resolves to `val`.
        """
        return only([node for node in self._plain_calls_in_stmt_at_line(frame.f_lineno)
                     if resolve_var(frame, node.func.id) == val])


file_info = lru_cache()(FileInfo)


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

    def __init__(self, frame, call: ast.Call):
        self.frame = frame
        self.call = call

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

    @property
    def file_info(self):
        """
        Returns an instance of FileInfo for the file where this frame is executed.
        """
        return FileInfo.for_frame(self.frame)

    def get_source(self, node: ast.AST) -> str:
        """
        Returns a string containing the source code of an AST node in the
        same file as this call.
        """
        return self.file_info.asttokens().get_text(node)


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


def resolve_var(frame, name: str):
    """
    Returns the value of a variable name in a frame.

    Equivalent to eval(name, frame.f_globals, frame.f_globals)
    (as long as 'name' is just an identifier)
    but faster and safer.
    """
    for ns in frame.f_locals, frame.f_globals, frame.f_builtins:
        try:
            return ns[name]
        except KeyError:
            pass
    raise NameError(name)


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
        if instance is None or owner is ModuleWrapper:
            spl = self
        else:
            # Functions are descriptors, which allow methods to
            # automatically bind the self argument.
            # Here we have to manually invoke that.
            method = self.func.__get__(instance, owner)
            spl = Spell(method)

        # Find the frame where the spell is being called.
        # Ignore functions decorated with @no_spells
        # or that aren't defined in source code we can find.
        frame = sys._getframe(1)
        while frame.f_code in self._excluded_codes or frame.f_code.co_filename.startswith('<'):
            frame = frame.f_back

        # If the spell is being accessed as part of a call,
        # e.g. obj.<spell name>(...), get that Call node
        call = FileInfo.for_frame(frame)._attr_call_at(
            frame.f_lineno, self.func.__name__)

        # The attribute is being accessed without calling it,
        # e.g. just `f = obj.<spell name>`
        # Return the spell as is so it can be called later
        if call is None:
            return spl

        # The spell is being called. Bind the FrameInfo
        return spl.at(FrameInfo(frame, call))

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
        call = FileInfo.for_frame(frame)._plain_call_at(frame, self)
        return self.at(FrameInfo(frame, call))(*args, **kwargs)

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


class ModuleWrapper(wrapt.ObjectProxy):
    """
    Wrapper around a module that looks and behaves exactly like
    the module it wraps, except that wrap_module attaches spells
    to this class to make them work as descriptors.
    """

    @no_spells
    def __getattribute__(self, item):
        # This method shouldn't be needed, it's a workaround of a bug
        # See https://github.com/GrahamDumpleton/wrapt/issues/101#issuecomment-299187363
        return object.__getattribute__(self, item)


def wrap_module(module_name: str, globs: dict):
    """
    Anywhere a spell is defined at the global level, put:

        wrap_module(__name__, globals())

    at the end of the module. This is needed for the following
    code to work:

        import mymodule

        mymodule.some_spell(...)

    """

    for name, value in globs.items():
        if isinstance(value, Spell):
            setattr(ModuleWrapper, name, value)
    sys.modules[module_name] = ModuleWrapper(sys.modules[module_name])
