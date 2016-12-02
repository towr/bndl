Getting started
===============


The main commands to use BNDL are ``bndl-compute-shell`` and ``bndl-compute-workers``.


ComputeContext
--------------
The main entry point for using BNDL Compute is an instance of :class:`bndl.compute.context.ComputeContext`. This class
provides methods to load :doc:`./datasets` on which :doc:`./transformations` can be applied.

For example to take the mean of 0 through 9:

.. code :: pycon

    >>> ctx.range(10).mean()
    4.5

Or to count the number of bytes in the files of the current working directory and everything below
it: 

.. code :: pycon

    >>> ctx.files('.').values().map(len).sum()
    73970628



Starting the Compute shell
--------------------------

The BNDL Compute Shell is an interactive python shell (using ipython if installed) which starts
local workers and/or connects with worker seed nodes. 

.. program-output:: bndl-compute-shell --help

By default the Compute shell starts workers as ``bndl-compute-workers`` unless ``--seeds`` is set.


Starting Compute workers
------------------------

Workers can be started with ``bndl-compute-workers``:

.. program-output:: bndl-compute-workers --help

By default as many workers as there are CPU cores (as indicated by ``os.cpu_count()``) are started.
Set ``--listen-addresses`` to a (space separated) list of host[:port] values to bind the hosts to
a certain host (and port). The default port for BNDL is 5000. Free ports are automatically selected
for the workers.


From a python script
--------------------

Python scripts can use the ``ctx`` global from ``bndl.compute.run`` to acquire a ComputeContext_:

.. code:: pycon

    >>> from bndl.compute.run import ctx
    >>> ctx.range(1000).map(str).map(len).stats()
    <Stats count=1000, mean=2.890000000000001, min=1.0, max=3.0, var=0.11789999999999999, stdev=0.3433656942677879, skew=-3.2053600735213332, kurt=10.25131920569249>