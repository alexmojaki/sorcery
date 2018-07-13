from .core import spell, no_spells, wrap_module

from .spells import unpack_keys, unpack_attrs, args_with_source, dict_of, print_args, call_with_name, delegate_to_attr, \
    maybe, select_from, magic_kwargs, assigned_names

__version__ = '0.0.1'

wrap_module(__name__, globals())
