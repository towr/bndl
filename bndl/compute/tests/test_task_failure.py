import time

from bndl.compute.tests import DatasetTest
from bndl.execute import TaskCancelled
from bndl.rmi import InvocationException


class TaskFailureTest(DatasetTest):
    def test_assert_raises(self):
        with self.assertRaises(Exception):
            self.ctx.range(10).map(lambda i: exec("raise ValueError('test')")).collect()


    def test_cancel(self):
        executed = self.ctx.accumulator(set())
        cancelled = self.ctx.accumulator(set())
        failed = self.ctx.accumulator(set())

        def task(idx):
            try:
                nonlocal executed, cancelled, failed
                executed.update('add', idx)
                for _ in range(10):
                    time.sleep(idx / 100)
            except TaskCancelled:
                cancelled.update('add', idx)
            except Exception:
                failed.update('add', idx)
                raise

            raise ValueError(idx)

        try:
            self.ctx.range(1, self.ctx.worker_count * 2 + 1, pcount=self.ctx.worker_count * 2).map(task).execute()
        except InvocationException as exc:
            self.assertIsInstance(exc.__cause__, ValueError)

        time.sleep((self.ctx.worker_count * 2 + 1) / 5)

        self.assertEqual(len(executed.value), self.ctx.worker_count)
        self.assertEqual(len(cancelled.value), self.ctx.worker_count - 1)
        self.assertEqual(len(failed.value), 0)
