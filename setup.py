import os
import re

from setuptools import setup

package = 'sorcery'

# __version__ is defined inside the package, but we can't import
# it because it imports dependencies which may not be installed yet,
# so we extract it manually
init_path = os.path.join(os.path.dirname(__file__),
                         package,
                         '__init__.py')
with open(init_path) as f:
    contents = f.read()
__version__ = re.search(r"__version__ = '([.\d]+)'", contents).group(1)

install_requires = [
    'executing',
    'littleutils>=0.2.1',
    'asttokens',
    'wrapt',
]

setup(name=package,
      version=__version__,
      description='Dark magic delights in Python',
      url='https://github.com/alexmojaki/' + package,
      author='Alex Hall',
      author_email='alex.mojaki@gmail.com',
      license='MIT',
      packages=[package],
      install_requires=install_requires,
      classifiers=[
          'License :: OSI Approved :: MIT License',
          'Programming Language :: Python',
          'Programming Language :: Python :: 3',
          'Programming Language :: Python :: 3.5',
          'Programming Language :: Python :: 3.6',
          'Programming Language :: Python :: 3.7',
          'Programming Language :: Python :: 3.8',
      ],
      zip_safe=False)
