#!/usr/bin/env python

import os
import re

from Cython.Build.Dependencies import cythonize
from setuptools import setup, find_packages, Extension


ext = re.compile(r'\.pyx$')

extensions = cythonize([
    Extension(
        '.'.join((root.replace(os.sep, '.'), ext.sub('', f))),
        [os.path.join(root, f)]
    )
    for root, dirs, files in os.walk('bndl')
    for f in files
    if not root.endswith('tests')
    if ext.search(f)
])


setup(
    name='bndl',
    version='0.1.0',
    url='https://stash.tgho.nl/projects/THCLUSTER/repos/bndl/browse',
    description='Bundle compute resources with BNDL',
    long_description=open('README.md').read(),
    author='Frens Jan Rumph',
    author_email='mail@frensjan.nl',

    packages=(
        find_packages(exclude=["*.tests", "*.tests.*"])
    ),

    include_package_data=True,
    zip_safe=False,

    setup_requires=[
        'cython'
    ],

    install_requires=[
        'sortedcontainers',
        'cloudpickle',
        'cytoolz',
        'numpy',
        'flask',
        'mmh3',
        'scandir',
    ],

    extras_require=dict(
        shell=['ipython'],
        dev=[
            'cython',
            'pytest',
            'pytest-cov',
            'pylint',
            'flake8',
            'sphinx',
            'sphinx-autobuild',
        ],
    ),

    ext_modules=extensions,

    entry_points=dict(
        console_scripts=[
            'bndl-compute-shell = bndl.compute.shell:main [shell]',
            'bndl-compute-workers = bndl.compute.worker:run_workers',
            'bndl-supervisor = bndl.util.supervisor:main',
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
