#!/usr/bin/env python

import os
import re

from setuptools import setup, find_packages, Extension

import bndl


install_requires = [
    'sortedcontainers',
    'cloudpickle>=0.2.1',
    'cytoolz',
    'numpy',
    'scipy',
    'pandas',
    'flask',
    'mmh3',
    'scandir',
    'psutil',
    'tblib',
    'marisa_trie',
    'yappi<=0.93',
]

dev_requires = [
    'cython<0.25',
    'pytest',
    'pytest-cov',
    'pylint',
    'flake8',
    'sphinx',
    'sphinx-autobuild',
    'sphinx-rtd-theme',
    'sphinxcontrib-programoutput',
]


ext = re.compile(r'\.pyx$')

extensions = [
    Extension(
        '.'.join((root.replace(os.sep, '.'), ext.sub('', f))),
        [os.path.join(root, f)]
    )
    for root, dirs, files in os.walk('bndl')
    for f in files
    if not root.endswith('tests')
    if ext.search(f)
]


try:
    from Cython.Build import cythonize
    extensions = cythonize(extensions, compiler_directives={
        'language_level': 3
    })
except ImportError:
    pass


if __name__ == '__main__':
    setup(
        name='bndl',
        version=bndl.__version__,
        url='https://stash.tgho.nl/projects/THCLUSTER/repos/bndl/browse',
        description='Bundle compute resources with BNDL',
        long_description=open('README.rst').read(),
        author='Frens Jan Rumph',
        author_email='mail@frensjan.nl',

        packages=(
            find_packages(exclude=["*.tests", "*.tests.*"])
        ),

        include_package_data=True,
        zip_safe=False,

        install_requires=install_requires,
        extras_require=dict(
            dev=dev_requires,
        ),
        ext_modules=extensions,

        entry_points=dict(
            console_scripts=[
                'bndl-compute-shell = bndl.compute.shell:main',
                'bndl-compute-workers = bndl.compute.worker:run_workers',
            ],
        ),

        classifiers=[
            'Development Status :: 3 - Alpha',
            'Intended Audience :: Developers',
            'Operating System :: OS Independent',
            'Programming Language :: Python',
            'Programming Language :: Python :: 3.4',
            'Programming Language :: Python :: 3.5',
        ],
    )
