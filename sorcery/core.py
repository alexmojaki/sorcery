import ast
import sys
import tokenize
from collections import defaultdict
from functools import lru_cache

import wrapt
from asttokens import ASTTokens
from cached_property import cached_property
from littleutils import only


class FileInfo(object):
    """
    Contains metadata about a python source file:

        - path: path to the file
        - source: text contents of the file
        - tree: AST parsed from the source
        - tokens: ASTTokens object for getting the source of specific AST nodes
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
    def for_frame(frame):
        return file_info(frame.f_code.co_filename)

    @cached_property
    def tokens(self):
        return ASTTokens(self.source, tree=self.tree, filename=self.path)

    @lru_cache()
    def _attr_call_at(self, line, name):
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
    def _plain_calls_in_stmt_at_line(self, lineno):
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
            stmt_containing_node(node)
            for node in
            self.nodes_by_line[lineno]})  # finds only statement at line - no semicolons allowed
        return [node for node in ast.walk(stmt)
                if isinstance(node, ast.Call) and
                isinstance(node.func, ast.Name)]

    def _plain_call_at(self, frame, val):
        """
        Returns the Call node currently being evaluated in this frame where
        the callable is just a variable name, not an attribute or some other expression,
        and that name resolves to `val`.
        """
        return only([node for node in self._plain_calls_in_stmt_at_line(frame.f_lineno)
                     if _resolve_var(frame, node.func.id) == val])


file_info = lru_cache()(FileInfo)


class FrameInfo(object):

    def __init__(self, frame, call):
        self.frame = frame
        self.call = call

    def assigned_names(self, *, allow_one: bool = False, allow_loops: bool = False):
        return nearest_assigned_names(self.call,
                                      allow_one=allow_one,
                                      allow_loops=allow_loops)

    @property
    def file_info(self):
        return FileInfo.for_frame(self.frame)


@lru_cache()
def stmt_containing_node(node):
    while not isinstance(node, ast.stmt):
        node = node.parent
    return node


@lru_cache()
def nearest_assigned_names(node, allow_one: bool, allow_loops: bool):
    while hasattr(node, 'parent'):
        node = node.parent

        if isinstance(node, ast.Assign):
            target = only(node.targets)
        elif isinstance(node, (ast.For, ast.comprehension)) and allow_loops:
            target = node.target
        else:
            continue

        names = node_names(target)
        if len(names) > 1 or allow_one:
            break
    else:
        raise TypeError('No assignment found')

    return names, node


def node_names(node):
    if isinstance(node, (ast.Tuple, ast.List)):
        names = tuple(node_name(x) for x in node.elts)
    else:
        names = (node_name(node),)
    return names


def node_name(node):
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


def _resolve_var(frame, name):
    for ns in frame.f_locals, frame.f_globals, frame.f_builtins:
        try:
            return ns[name]
        except KeyError:
            pass
    raise NameError(name)


class Spell(object):
    excluded = set()

    def __init__(self, func):
        self.func = func

    def __get__(self, instance, owner):
        if instance is None or owner is ModuleWrapper:
            spl = self
        else:
            method = self.func.__get__(instance, owner)
            spl = Spell(method)

        frame = sys._getframe(1)
        while frame.f_code in self.excluded or frame.f_code.co_filename.startswith('<'):
            frame = frame.f_back

        call = FileInfo.for_frame(frame)._attr_call_at(
            frame.f_lineno, self.func.__name__)

        if call is None:
            return spl

        return spl[FrameInfo(frame, call)]

    def __getitem__(self, frame_info):
        @wrapt.decorator
        def wrapper(wrapped, _instance, args, kwargs):
            return wrapped(frame_info, *args, **kwargs)

        return wrapper(self.func)

    def __call__(self, *args, **kwargs):
        frame = sys._getframe(1)
        call = FileInfo.for_frame(frame)._plain_call_at(frame, self)
        return self[FrameInfo(frame, call)](*args, **kwargs)

    def __repr__(self):
        return '%s(%r)' % (
            self.__class__.__name__,
            self.func
        )


spell = Spell


def no_spells(func):
    Spell.excluded.add(func.__code__)
    return func


class ModuleWrapper(wrapt.ObjectProxy):
    @no_spells
    def __getattribute__(self, item):
        return object.__getattribute__(self, item)


def wrap_module(module_name, globs):
    for name, value in globs.items():
        if isinstance(value, Spell):
            setattr(ModuleWrapper, name, value)
    sys.modules[module_name] = ModuleWrapper(sys.modules[module_name])
