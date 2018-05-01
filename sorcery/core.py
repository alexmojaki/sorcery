import ast
import sys

from asttokens import ASTTokens
from cached_property import cached_property
from collections import defaultdict
from littleutils import file_to_string, only

try:
    from functools import lru_cache
except ImportError:
    # noinspection PyUnresolvedReferences,PyPackageRequirements
    from backports.functools_lru_cache import lru_cache

__version__ = '0.0.1'


class FileInfo(object):

    def __init__(self, path):
        self.source = file_to_string(path)
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
        options = [node for node in self.nodes_by_line[line]
                   if isinstance(node, ast.Call) and
                   isinstance(node.func, ast.Attribute) and
                   node.func.attr == name]
        if not options:
            return None

        if len(options) == 1:
            return options[0]

        raise ValueError('Found %s possible calls to %s' % (len(options), name))

    def _plain_call_at(self, frame, val):
        return only([node for node in self.nodes_by_line[frame.f_lineno]
                     if isinstance(node, ast.Call) and
                     isinstance(node.func, ast.Name) and
                     _resolve_var(frame, node.func.id) == val])


file_info = lru_cache()(FileInfo)


class FrameInfo(object):

    def __init__(self, frame, call):
        self.frame = frame
        self.call = call

    @property
    def stmt(self):
        return stmt_containing_node(self.call)

    @property
    def assigned_names(self):
        return nearest_assigned_names(self.call)

    @property
    def file_info(self):
        return FileInfo.for_frame(self.frame)


@lru_cache()
def stmt_containing_node(node):
    while not isinstance(node, ast.stmt):
        node = node.parent
    return node


@lru_cache()
def nearest_assigned_names(node):
    while not isinstance(node, (ast.stmt, ast.comprehension)):
        node = node.parent

    if isinstance(node, ast.Assign):
        target = only(node.targets)
    elif isinstance(node, (ast.For, ast.comprehension)):
        target = node.target
    else:
        raise TypeError('No assignment found')

    if isinstance(target, (ast.Tuple, ast.List)):
        names = tuple(_target_name(x) for x in target.elts)
    else:
        names = (_target_name(target),)

    return names, node


def _target_name(target):
    if isinstance(target, ast.Name):
        return target.id
    elif isinstance(target, ast.Attribute):
        return target.attr
    else:
        raise TypeError('Cannot extract name from %s' % target)


def _resolve_var(frame, name):
    for ns in frame.f_locals, frame.f_globals, frame.f_builtins:
        try:
            return ns[name]
        except KeyError:
            pass
    raise NameError(name)


class Spell(object):
    def __init__(self, func):
        self.func = func

    def __get__(self, instance, owner):
        frame = sys._getframe(1)
        call = FileInfo.for_frame(frame)._attr_call_at(
            frame.f_lineno, self.func.__name__)

        if call is None:
            return self

        return self[FrameInfo(frame, call)]

    def __getitem__(self, frame_info):
        def wrapper(*args, **kwargs):
            return self.func(frame_info, *args, **kwargs)

        return wrapper

    def __call__(self, *args, **kwargs):
        frame = sys._getframe(1)
        call = FileInfo.for_frame(frame)._plain_call_at(frame, self)
        return self[FrameInfo(frame, call)](*args, **kwargs)


spell = Spell
