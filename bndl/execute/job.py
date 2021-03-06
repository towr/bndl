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

from concurrent.futures import CancelledError, Future, TimeoutError
from datetime import datetime
from functools import lru_cache
from itertools import count
import logging

from bndl.net.connection import NotConnected
from bndl.util.lifecycle import Lifecycle


logger = logging.getLogger(__name__)



class Job(Lifecycle):
    '''
    A set of :class:`Tasks <Task>` which can be executed on a cluster of workers.
    '''
    _job_ids = count(1)

    def __init__(self, ctx, tasks, name=None, desc=None):
        super().__init__(name, desc)
        self.id = next(self._job_ids)
        self.ctx = ctx
        self.tasks = tasks


    def cancel(self):
        for task in self.tasks:
            task.cancel()
        super().cancel()


    @lru_cache()
    def group(self, name):
        return [t for t in self.tasks if t.group == name]



class Task(Lifecycle):
    '''
    Execution of a Task on a worker is the basic unit of scheduling in ``bndl.execute``.
    '''

    def __init__(self, ctx, task_id, *, priority=None, name=None, desc=None, group=None):
        super().__init__(name or 'task ' + str(task_id),
                         desc or 'unknown task ' + str(task_id))
        self.ctx = ctx
        self.id = task_id
        self.group = group

        self.priority = task_id if priority is None else priority
        self.future = None

        self.dependencies = []
        self.dependents = []
        self.executed_on = []
        self.attempts = 0


    def execute(self, scheduler, worker):
        '''
        Execute the task on a worker. The scheduler is provided as 'context' for the task.
        '''


    def cancel(self):
        '''
        Cancel execution (if not already done) of this task.
        '''
        if not self.done:
            super().cancel()


    def locality(self, workers):
        '''
        Indicate locality for executing this task on workers.

        Args:
            workers (sequence[worker]): The workers to determine the locality for.

        Returns:
            Sequence[(worker, locality), ...]: A sequence of worker - locality tuples. 0 is
            indifferent and can be skipped, -1 is forbidden, 1+ increasing locality.
        '''
        return ()


    @property
    def started(self):
        '''Whether the task has started'''
        return bool(self.future)


    @property
    def done(self):
        '''Whether the task has completed execution'''
        return self.future and self.future.done()


    @property
    def pending(self):
        return self.future and not self.future.done()


    @property
    def succeeded(self):
        try:
            return bool(self.future and not self.future.exception(0))
        except (CancelledError, TimeoutError):
            return False


    @property
    def failed(self):
        try:
            return bool(self.future and self.future.exception(0))
        except (CancelledError, TimeoutError):
            return False


    def set_executing(self, worker):
        '''Utility for sub-classes to register the task as executing on a worker.'''
        if self.cancelled:
            raise CancelledError()
        assert not self.pending, '%r pending' % self
        self.executed_on.append(worker.name)
        self.attempts += 1
        self.signal_start()


    def mark_done(self, result=None):
        ''''
        Externally' mark the task as done. E.g. because its 'side effect' (result) is already
        available).
        '''
        if not self.done:
            future = self.future = Future()
            future.set_result(result)
            if not self.started_on:
                self.started_on = datetime.now()
            self.signal_stop()


    def mark_failed(self, exc):
        '''
        'Externally' mark the task as failed. E.g. because the worker which holds the tasks' result
        has failed / can't be reached.
        '''
        future = self.future = Future()
        future.set_exception(exc)
        self.signal_stop()


    def result(self):
        '''
        Get the result of the task (blocks). Raises an exception if the task failed with one.
        '''
        assert self.future, 'task %r not yet scheduled' % self
        return self.future.result()


    def exception(self):
        '''Get the exception of the task (blocks).'''
        assert self.future, 'task %r not yet started' % self
        return self.future.exception()


    def executed_on_last(self):
        '''The name of the worker this task executed on last (if any).'''
        try:
            return self.executed_on[-1]
        except ValueError:
            return None


    def release(self):
        '''Release most resources of the task. Invoked after a job's execution is complete.'''
        if self.succeeded:
            self.future = None
        self.dependencies = []
        self.dependents = []
        if self.executed_on:
            self.executed_on = [self.executed_on[-1]]
        self.started_listeners.clear()
        self.stopped_listeners.clear()


    def __repr__(self):
        task_id = '.'.join(map(str, self.id)) if isinstance(self.id, tuple) else self.id
        if self.failed:
            state = ' failed'
        elif self.done:
            state = ' done'
        elif self.pending:
            state = ' pending'
        else:
            state = ''
        return '<%s %s%s>' % (self.__class__.__name__, task_id, state)



class RmiTask(Task):
    '''
    A task which performs a Remote Method Invocation to execute a method with positional and keyword arguments.
    '''

    def __init__(self, ctx, task_id, method, args=(), kwargs=None, *, priority=None, name=None, desc=None, group=None):
        super().__init__(ctx, task_id, priority=priority, name=name, desc=desc, group=group)
        self.method = method
        self.args = args
        self.kwargs = kwargs or {}
        self.handle = None


    def execute(self, scheduler, worker):
        self.set_executing(worker)
        future = self.future = Future()
        future2 = worker.service('tasks').execute_async(self.method, *self.args, **self.kwargs)
        # TODO remove future.worker, just for checking
        future2.worker = worker
        # TODO put time sleep here to test what happens if task
        # is done before adding callback (callback runs in this thread)
        future2.add_done_callback(self._task_scheduled)
        return future

    @property
    def _last_worker(self):
        if self.executed_on:
            return self.ctx.node.peers.get(self.executed_on[-1])


    def _task_scheduled(self, future):
        try:
            self.handle = future.result()
        except Exception as exc:
            self.mark_failed(exc)
        else:
            try:
                # TODO remove future.worker
                # assert future.worker == self._last_worker, '%r != %r' % (future.worker, self._last_worker)
                future = self._last_worker.service('tasks').get_task_result(self.handle)
                # TODO put time sleep here to test what happens if task
                # is done before adding callack (callback gets executed in this thread)
                future.add_done_callback(self._task_completed)
            except NotConnected as exc:
                self.mark_failed(exc)


    def _task_completed(self, future):
        try:
            self.handle = None
            result = future.result()
        except Exception as exc:
            if self.future:
                self.future.set_exception(exc)
            elif not isinstance(exc, NotConnected):
                if logger.isEnabledFor(logging.INFO):
                    logger.info('execution of %s on %s failed, but not expecting result',
                                self, self.executed_on_last(), exc_info=True)
        else:
            if self.future and not self.future.cancelled():
                self.future.set_result(result)
            else:
                logger.info('task %s (%s) completed, but not expecting result')
        finally:
            self.signal_stop()


    def cancel(self):
        super().cancel()

        if self.handle:
            logger.debug('canceling %s', self)
            self._last_worker.service('tasks').cancel_task(self.handle)
            self.handle = None

        if self.future:
            self.future = None


    def release(self):
        super().release()
        self.method = self.method.__name__
        self.handle = None
        self.args = None
        self.kwargs = None
        self.locality = None
