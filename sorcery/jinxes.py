import ast
from contextlib import contextmanager

from sorcery.core import spell


@spell
@contextmanager
def retry(frame_info):
    try:
        yield
    except:
        module = ast.Module(frame_info.stmt.body)
        frame = frame_info.frame
        code = compile(module, filename=frame.f_code.co_filename, mode='exec')
        exec(code, frame.f_globals, frame.f_locals)
