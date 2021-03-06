# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import signal

from cytoolz.itertoolz import groupby

from bndl.compute.run import create_ctx
from bndl.compute.worker import many_argparser
from bndl.util.exceptions import catch
from bndl.util.funcs import identity
from bndl.util.threads import dump_threads
import bndl


HEADER = r'''         ___ _  _ ___  _
Welcome | _ ) \| |   \| |
to the  | _ \ .` | |) | |__
        |___/_|\_|___/|____| shell.

Running BNDL version %s.
ComputeContext available as ctx.''' % bndl.__version__


argparser = argparse.ArgumentParser(parents=[many_argparser])
argparser.prog = 'bndl.compute.shell'
argparser.add_argument('--worker-count', nargs='?', type=int, default=None, dest='worker_count',
                       help='The number of BNDL workers to start (defaults to 0 if seeds is set).')
argparser.add_argument('--conf', nargs='*', default=(),
                       help='BNDL configuration in "key=value" format')


def main():
    signal.signal(signal.SIGUSR1, dump_threads)

    try:
        args = argparser.parse_args()
        config = bndl.conf

        if args.listen_addresses:
            config['bndl.net.listen_addresses'] = args.listen_addresses
        if args.seeds:
            config['bndl.net.seeds'] = args.seeds
            config['bndl.compute.worker_count'] = 0
        if args.worker_count is not None:
            config['bndl.compute.worker_count'] = args.worker_count

        config['bndl.run.numactl'] = args.numactl
        config['bndl.run.pincore'] = args.pincore
        config['bndl.run.jemalloc'] = args.jemalloc

        config.update(*args.conf)

        ctx = create_ctx(config)
        ns = dict(ctx=ctx)

        if config['bndl.net.seeds'] or config['bndl.compute.worker_count'] != 0:
            print('Connecting with workers ...', end='\r')
            worker_count = ctx.await_workers(args.worker_count)
            node_count = len(groupby(identity, [tuple(sorted(worker.ip_addresses())) for worker in ctx.workers]))
            header = HEADER + '\nConnected with %r workers on %r nodes.' % (worker_count, node_count)
        else:
            header = HEADER

        try:
            import IPython
            IPython.embed(header=header, user_ns=ns)
        except ImportError:
            import code
            code.interact(header, local=ns)
    finally:
        with catch():
            ctx.stop()


if __name__ == '__main__':
    main()
