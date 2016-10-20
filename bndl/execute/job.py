from concurrent.futures import CancelledError
from itertools import chain, count
from queue import Queue
import abc
import logging
import threading

from bndl.util.lifecycle import Lifecycle


logger = logging.getLogger(__name__)


class Job(Lifecycle):

    _jobids = count(1)

    def __init__(self, ctx, name=None, desc=None):
        super().__init__(name, desc)
        self.id = next(self._jobids)
        self.ctx = ctx
        self.stages = []


    def execute(self, workers, eager=True, ordered=True, concurrency=1):
        required_workers_available = all(
            worker in workers
            for stage in self.stages
            for task in stage.tasks
            for worker in task.allowed_workers
        )
        if not required_workers_available:
            raise RuntimeError('Not all required workers are available')

        self.signal_start()

        logger.info('executing job %s with stages %s', self, self.stages)

        try:
            for stage in self.stages:
                if not self.running:
                    break
                logger.info('executing stage %s with %s tasks', stage, len(stage.tasks))
                is_last = stage == self.stages[-1]
                stage.add_listener(self._on_stage_event)
                yield stage.execute(workers,
                                    eager=(not is_last) or eager,
                                    ordered=ordered,
                                    concurrency=concurrency)
        except (Exception, GeneratorExit):
            self.cancel()
            raise


    def _on_stage_event(self, stage):
        if stage.stopped and stage == self.stages[-1]:
            self.signal_stop()
        if stage.cancelled:
            self.cancel()


    def cancel(self):
        for stage in self.stages:
            if not stage.stopped:
                stage.cancel()
        super().cancel()


    @property
    def tasks(self):
        return list(chain.from_iterable(stage.tasks for stage in self.stages))



class Stage(Lifecycle):

    def __init__(self, stage_id, job, name=None, desc=None):
        super().__init__(name, desc)
        self.id = stage_id
        self.job = job
        self.tasks = []


    def execute(self, workers, eager=True, ordered=True, concurrency=1):
        self.signal_start()

        for task in self.tasks:
            # clean up preferred worker list given the available workers
            task.preferred_workers = [worker for worker
                                      in task.preferred_workers
                                      if worker in workers]

        try:
            if eager:
                yield from self._execute_eagerly(workers, ordered=ordered, concurrency=concurrency)
            else:
                yield from self._execute_onebyone(workers)
        except (Exception, KeyboardInterrupt):
            self.cancel()
            raise


    def _execute_eagerly(self, workers, ordered, concurrency):
        workers_available = Queue()
        for _ in range(concurrency):
            for worker in workers:
                workers_available.put(worker)

        to_schedule = self.tasks[:]
        done = Queue()
        sentinel = object()
        scheduled = threading.Semaphore(0)

        def task_done(task, worker):
            workers_available.put(worker)
            done.put(task)

        def schedule_tasks():
            while to_schedule:
                # only step if there is a worker available
                worker = workers_available.get()
                # break if sentinel received
                if worker == sentinel:
                    break

                idx, task = None, None
                for idx, task in enumerate(to_schedule):
                    if task.preferred_workers:
                        if worker in task.preferred_workers:
                            break
                        else:
                            idx, task = None, None
                    elif task.allowed_workers:
                        if worker in task.allowed_workers:
                            break
                        else:
                            idx, task = None, None
                    else:
                        break

                if not task:
                    workers_available.put(worker)
                else:
                    try:
                        del to_schedule[idx]
                        future = task.execute(worker)
                        future.add_done_callback(lambda future, task=task, worker=worker: task_done(task, worker))
                        scheduled.release()
                    except CancelledError:
                        pass

        task_driver = threading.Thread(target=schedule_tasks, daemon=True,
                                       name='bndl-task-driver-%s-%s' % (self.job.id, self.id))
        task_driver.start()

        try:
            if ordered:
                next_task_idx = 0
                while next_task_idx < len(self.tasks):
                    next_task = self.tasks[next_task_idx]
                    if next_task.started:
                        yield next_task.result()
                        next_task_idx += 1
                    else:
                        scheduled.acquire()
            else:
                for _ in range(len(self.tasks)):
                    yield done.get().result()
        except Exception:
            to_schedule.clear()
            workers_available.put(sentinel)
            raise

        task_driver.join()
        self.signal_stop()


    def _execute_onebyone(self, workers):
        for task in self.tasks:
            if task.preferred_workers:
                worker = task.preferred_workers[0]
            elif task.allowed_workers:
                worker = task.allowed_workers[0]
            else:
                worker = workers[0]
            future = task.execute(worker)
            yield future.result()
        self.signal_stop()


    def cancel(self):
        for task in self.tasks:
            if not task.stopped:
                task.cancel()
        super().cancel()


    def __repr__(self):
        return 'Stage(id=%s)' % self.id



class Task(Lifecycle, metaclass=abc.ABCMeta):

    def __init__(self, task_id, stage, method, args, kwargs,
                 preferred_workers=None, allowed_workers=None,
                 name=None, desc=None):
        super().__init__(name, desc)
        self.id = task_id
        self.stage = stage
        self.method = method
        self.args = args or ()
        self.kwargs = kwargs or {}
        self.preferred_workers = preferred_workers
        self.allowed_workers = allowed_workers
        self.task_id = None
        self.future = None
        self.executed_on = []

    def execute(self, worker):
        if self.cancelled:
            raise CancelledError()
        args = self.args
        kwargs = self.kwargs

        self.signal_start()
        self.executed_on.append(worker)
        self.task_id = worker.run_task_async(self.method, *args, **kwargs).result()
        self.future = worker.get_task_result(self.task_id)
        self.future.add_done_callback(lambda future: self.signal_stop())
        return self.future

    @property
    def started(self):
        return bool(self.future)

    @property
    def done(self):
        return self.future and self.future.done()

    @property
    def failed(self):
        try:
            return bool(self.future and self.future.done() and self.future.exception())
        except CancelledError:
            return False

    def result(self):
        assert self.future, 'task not yet scheduled'
        try:
            return self.future.result()
        finally:
            self._release_resources()

    def cancel(self):
        if not self.done:
            try:
                if self.task_id:
                    self.executed_on[-1].cancel_task(self.task_id).result()
                if self.future:
                    self.future.cancel()
                super().cancel()
            finally:
                self._release_resources()

    def _release_resources(self):
        # release resources if successful
        # (otherwise an exception is raised)
        self.future = None
        self.args = None
        self.kwargs = None
        self.preferred_workers = None
        self.allowed_workers = None
