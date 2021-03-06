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

from uuid import uuid4
import concurrent.futures
import json
import logging
import marshal
import pickle

from bndl.util import serialize, threads
from bndl.util.conf import Float
from bndl.util.funcs import identity
from cytoolz.functoolz import compose


min_block_size = Float(4, desc='The maximum size of a block in megabytes.')  # MB
max_block_size = Float(16, desc='The minimum size of a block in megabytes.')  # MB


logger = logging.getLogger(__name__)
download_coordinator = threads.Coordinator()


MISSING = 'bndl.compute.broadcast.MISSING'



class BroadcastManager(object):
    def __init__(self, worker):
        self.worker = worker


    def unpersist_broadcast_values(self, src, name):
        self.worker.service('blocks').remove_blocks(name)
        del download_coordinator[name]



def broadcast(ctx, value, serialization='auto', deserialization=None):
    '''
    Broadcast data to workers.

    Args:

        value (object): The value to broadcast.
        serialization (str): The format to serialize the broadcast value into. Must be one of auto,
            pickle, marshal, json, binary or text.
        deserialization (None or function(bytes)):

    Data can be 'shipped' along to workers in the closure of e.g. a mapper function, but in that
    case the data is sent once for every partition (task to be precise). For 'larger' values this
    may be wasteful. Use this for instance with lookup tables of e.g. a MB or more.

    Note that the broadcast data is loaded on each worker (but only if the broadcast variable is
    used). The machine running the workers should thus have enough memory to spare.

    If deserialization is set serialization must *not* be set and value must be of type `bytes`.
    Otherwise serialize is used to serialize value and its natural deserialization counterpart is
    used (e.g. bytes.decode followed by json.loads for the 'json' serialization format).

    Example usage::

        >>> tbl = ctx.broadcast(dict(zip(range(4), 'abcd')))
        >>> ctx.range(4).map(lambda i: tbl.value[i]).collect()
        ['a', 'b', 'c', 'd']

    '''
    if serialization is not None:
        if deserialization is not None:
            raise ValueError("Can't specify both serialization and deserialization")
        elif serialization == 'auto':
            marshalled, data = serialize.dumps(value)
            deserialization = marshal.loads if marshalled else pickle.loads
        elif serialization == 'pickle':
            data = pickle.dumps(value)
            deserialization = pickle.loads
        elif serialization == 'marshal':
            data = marshal.dumps(value)
            deserialization = marshal.loads
        elif serialization == 'json':
            data = json.dumps(value).encode()
            deserialization = compose(json.loads, bytes.decode)
        elif serialization == 'binary':
            data = value
            deserialization = identity
        elif serialization == 'text':
            data = value.encode()
            deserialization = bytes.decode
        else:
            raise ValueError('Unsupported serialization %s' % serialization)
    elif not deserialization:
        raise ValueError('Must specify either serialization or deserialization')
    else:
        data = value

    key = str(uuid4())
    min_block_size = int(ctx.conf.get('bndl.compute.broadcast.min_block_size') * 1024 * 1024)
    max_block_size = int(ctx.conf.get('bndl.compute.broadcast.max_block_size') * 1024 * 1024)
    block_size = max_block_size \
                 if min_block_size == max_block_size else \
                 (ctx.worker_count * 2, min_block_size, max_block_size)
    block_spec = ctx.node.service('blocks').serve_data(key, data, block_size)
    return BroadcastValue(ctx, ctx.node.name, block_spec, deserialization)


class BroadcastValue(object):
    def __init__(self, ctx, seeder, block_spec, deserialize):
        self.ctx = ctx
        self.seeder = seeder
        self.block_spec = block_spec
        self.deserialize = deserialize


    @property
    def value(self):
        return download_coordinator.coordinate(self._get, self.block_spec.name)


    def _get(self):
        node = self.ctx.node
        blocks_svc = node.service('blocks')
        blocks = blocks_svc.get(self.block_spec, node.peers.filter(node_type='worker'))

        val = self.deserialize(b''.join(blocks))

        if node.name != self.block_spec.seeder:
            blocks_svc.remove_blocks(self.block_spec.name, from_peers=False)

        return val


    def unpersist(self, block=False, timeout=None):
        node = self.ctx.node
        name = self.block_spec.name
        assert node.name == self.block_spec.seeder
        node.service('broadcast').unpersist_broadcast_values(node, name)
        requests = [peer.service('broadcast').unpersist_broadcast_values
                   for peer in node.peers.filter()]
        if timeout:
            requests = [request.with_timeout(timeout) for request in requests]
        requests = [request(name) for request in requests]
        if block:
            for request in requests:
                try:
                    request.result()
                except concurrent.futures.TimeoutError:
                    pass
                except Exception:
                    logger.warning('error while unpersisting %s', name, exc_info=True)


    def __del__(self):
        if self.ctx.node and self.ctx.node.name == self.block_spec.seeder:
            self.unpersist()
