from .core import spell, no_spells

from .spells import unpack_keys, unpack_attrs, args_with_source, dict_of, print_args, call_with_name, delegate_to_attr, \
    maybe, select_from, magic_kwargs, assigned_names, switch, timeit

try:
    from .version import __version__
except ImportError:  # pragma: no cover
    # version.py is auto-generated with the git tag when building
    __version__ = "???"
