from functools import partial
from types import MethodType
import logging
import threading
import weakref

from bndl.util import strings


logger = logging.getLogger(__name__)


class AccumulatorService:
    def __init__(self):
        self.accumulators = {}
        self.locks = {}


    def _register_accumulator(self, accumulator):
        aid = accumulator.id
        def remove_lock(x):
            del self.locks[aid]
        self.accumulators[aid] = weakref.proxy(accumulator, remove_lock)
        self.locks[aid] = threading.Lock()


    def _deregister_accumulator(self, accumulator_id):
        del self.accumulators[accumulator_id]
        del self.locks[accumulator_id]


    def _update_accumulator(self, src, accumulator_id, op, value):
        try:
            lock = self.locks[accumulator_id]
        except KeyError:
            logger.debug('received update for unknown accumulator %s',
                         accumulator_id)
        try:
            with lock:
                accumulator = self.accumulators[accumulator_id]
                if op == '+':
                    accumulator.value += value
                elif op == '-':
                    accumulator.value -= value
                elif op == '*':
                    accumulator.value *= value
                elif op == '/':
                    accumulator.value /= value
                elif op == '<':
                    accumulator.value <<= value
                elif op == '>':
                    accumulator.value >>= value
                elif op == '&':
                    accumulator.value &= value
                elif op == '|':
                    accumulator.value |= value
                else:
                    getattr(accumulator.value, op)(value)
        except Exception:
            logger.exception('Unable to update_accumulator with id %s with operator '
                             '%s and value %s', accumulator_id, op, value)



class AccumulatorProxy(object):
    def __init__(self, ctx, host, accumulator_id):
        self.ctx = ctx
        self.host = host
        self.id = accumulator_id


    def update(self, op, value):
        self.ctx.node.peers[self.host]._update_accumulator(self.id, op, value)
        return self

    def __iadd__(self, value):
        return self.update('+', value)

    def __isub__(self, value):
        return self.update('-', value)

    def __imul__(self, value):
        return self.update('*', value)

    def __itruediv__(self, value):
        return self.update('/', value)

    def __ilshift__(self, value):
        return self.update('<', value)

    def __irshift__(self, value):
        return self.update('>', value)

    def __iand__(self, value):
        return self.update('&', value)

    def __ior__(self, value):
        return self.update('|', value)



class Accumulator(object):
    '''
    A value on which commutative and associative operations can be performed from remote workers.
    '''

    def __init__(self, ctx, host, initial, accumulator_id=None):
        self.ctx = ctx
        self.host = host
        self.value = initial
        self.id = accumulator_id or strings.random(8)


    def __reduce__(self):
        return AccumulatorProxy, (self.ctx, self.host, self.id)