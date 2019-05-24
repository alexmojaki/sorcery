import ast
import dis
import inspect
import sys
import tokenize
from collections import defaultdict
from functools import lru_cache, partial
from types import CodeType
from typing import Tuple, List

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

    def _call_at(self, frame):
        stmts = {
            statement_containing_node(node)
            for node in
            self.nodes_by_line[frame.f_lineno]}
        return CallFinder(frame, stmts).result


sentinel = 'io8urthglkjdghvljusketgIYRFYUVGHFRTBGVHKGF78678957647698'
special_code_names = ('<listcomp>', '<dictcomp>', '<setcomp>', '<lambda>', '<genexpr>')


class CallFinder(object):
    def __init__(self, frame, stmts):
        self.frame = frame
        self.stmts = stmts
        a_stmt = self.a_stmt = list(stmts)[0]
        body = self.body = only(lst for lst in get_node_bodies(a_stmt.parent)
                                if a_stmt in lst)
        stmts = self.stmts = sorted(stmts, key=body.index)

        frame_offset_relative_to_stmt = frame.f_lasti

        if frame.f_code.co_name not in special_code_names:
            frame_offset_relative_to_stmt -= self.stmt_offset()

        function = ast.FunctionDef(
            name='<function>',
            body=stmts,
            args=ast.arguments(args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
            decorator_list=[],
        )
        module = ast.Module(body=[function])
        ast.copy_location(function, stmts[0])
        instruction_index, instruction = only(
            (i, instruction)
            for i, instruction in enumerate(_call_instructions(_stmt_instructions(module, frame.f_code)))
            if instruction.offset == frame_offset_relative_to_stmt
        )

        calls = [
            node
            for stmt in stmts
            for node in ast.walk(stmt)
            if isinstance(node, ast.Call)
        ]

        for i, call in enumerate(calls):
            keyword = ast.keyword(arg=None, value=ast.Str(sentinel))
            calls[i].keywords.append(keyword)
            try:
                ast.fix_missing_locations(calls[i])
                instructions = list(enumerate(_stmt_instructions(module, frame.f_code)))
            finally:
                calls[i].keywords.pop()
            
            indices = [i for i, instruction in instructions if instruction.argval == sentinel]
            if not indices:
                continue
            arg_index = only(indices)
            new_instruction = [instruction for i, instruction in instructions
                               if i > arg_index
                               if instruction.opname.startswith('CALL_')
                               ][0]

            call_instructions = [inst for i, inst in instructions if inst.opname.startswith('CALL_')]
            new_instruction_index = only([i for i, instruction in enumerate(call_instructions)
                                          if instruction is new_instruction])

            if new_instruction_index == instruction_index:
                break
        else:
            raise Exception

        self.result = calls[i]
    
    def stmt_offset(self):
        body = self.body
        stmts = self.stmts
        a_stmt = self.a_stmt
        
        stmt_index = body.index(stmts[0])
        body[stmt_index] = ast.Expr(value=ast.List(elts=[ast.Str(sentinel)], ctx=ast.Load()))

        try:
            ast.fix_missing_locations(a_stmt.parent)

            parent_block = get_containing_block(a_stmt)
            if isinstance(parent_block, ast.Module):
                assert self.frame.f_code.co_name == '<module>'
                module = parent_block
                extract = False
            else:
                module = ast.Module(body=[parent_block])
                extract = True
            instructions = _stmt_instructions(module, extract=extract)

            return only([
                instruction for instruction in instructions
                if instruction.argval == sentinel]).offset
        finally:
            body[stmt_index] = stmts[0]


def get_node_bodies(node):
    for name, field in ast.iter_fields(node):
        if isinstance(field, list):
            yield field


def get_containing_block(node):
    while True:
        node = node.parent
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            return node


def _stmt_instructions(module, matching_code=None, extract=True):
    code = compile(module, '<mod>', 'exec')
    if extract:
        stmt_code = only([c for c in code.co_consts
                          if isinstance(c, CodeType)])
        code = find_code(stmt_code, matching_code)
    return list(dis.get_instructions(code))


def _call_instructions(instructions):
    return (i for i in instructions if i.opname.startswith('CALL_'))


def find_code(root_code, matching):
    if matching is None or matching.co_name not in special_code_names:
        return root_code

    code_options = []  # type: List[CodeType]

    def finder(code):
        # type: (CodeType) -> None
        for const in code.co_consts:  # type: CodeType
            if not inspect.iscode(const):
                continue
            matches = (const.co_firstlineno == matching.co_firstlineno and
                       const.co_name == matching.co_name)
            if matches:
                code_options.append(const)
            finder(const)

    finder(root_code)
    return only(code_options)


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

        while frame.f_code in self._excluded_codes or frame.f_code.co_filename.startswith('<'):
            frame = frame.f_back

        call = FileInfo.for_frame(frame)._call_at(frame)
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
