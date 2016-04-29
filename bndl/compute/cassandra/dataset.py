import logging

from bndl.compute.cassandra import partitioner
from bndl.compute.cassandra.session import cassandra_session
from bndl.compute.dataset.base import Dataset, Partition
from bndl.util import collection
from cassandra.concurrent import execute_concurrent_with_args
from cassandra.query import tuple_factory, named_tuple_factory, dict_factory


logger = logging.getLogger(__name__)


class CassandraScanDataset(Dataset):
    def __init__(self, ctx, keyspace, table, concurrency=10, contact_points=None):
        '''
        Create a scan across keyspace.table.
        
        :param ctx:
            The compute context.
        :param keyspace: str
            Keyspace of the table to scan.
        :param table: str
            Name of the table to scan.
        :param concurrency: int > 0
            Maximum number of concurrent queries per partition.
            concurrency * ctx.worker_count is the maximum number of concurrent
            queries in total.
        :param contact_points: None or [str,str,str,...]
            None to use the default contact points or a list of contact points
            or a comma separated string of contact points.
        '''
        super().__init__(ctx)
        self.keyspace = keyspace
        self.table = table
        self.contact_points = contact_points
        self.concurrency = concurrency
        self._row_factory = named_tuple_factory

        with ctx.cassandra_session(contact_points=self.contact_points) as session:
            keyspace_meta = session.cluster.metadata.keyspaces[self.keyspace]
            table_meta = keyspace_meta.tables[self.table]

        self._select = '*'
        self._limit = None
        self._where = '''
            token({partition_key_column_names}) > ? and
            token({partition_key_column_names}) <= ?
            '''.format(
                partition_key_column_names=', '.join(c.name for c in table_meta.partition_key)
            )


    def count(self, push_down=None):
        if push_down is True or (not self.cached and push_down is None):
            return self.select('count(*)').as_tuples().map(collection.getter(0)).sum()
        else:
            return super().count()


    def as_tuples(self):
        return self._with('_row_factory', tuple_factory)

    def as_dicts(self):
        return self._with('_row_factory', dict_factory)

    def select(self, *columns):
        return self._with('_select', ', '.join(columns))


    def limit(self, num):
        wlimit = self._with('_limit', int(num))
        wlimit.concurrency = min(wlimit.concurrency, num)
        return wlimit

    def itake(self, num):
        if not self.cached and not self._limit:
            return self.limit(num).itake(num)
        else:
            return super().itake(num)


    def parts(self):
        with cassandra_session(self.ctx, contact_points=self.contact_points) as session:
            partitions = partitioner.partition_ranges(session, self.keyspace, self.table)
            while len(partitions) < self.ctx.default_pcount:
                repartitioned = []
                for replicas, token_ranges in partitions:
                    if len(token_ranges) == 1:
                        continue
                    mid = len(token_ranges) // 2
                    repartitioned.append((replicas, token_ranges[:mid]))
                    repartitioned.append((replicas, token_ranges[mid:]))
                if len(repartitioned) == len(partitions):
                    break
                partitions = repartitioned


        return [
            CassandraScanPartition(self, i, replicas, token_ranges)
            for i, (replicas, token_ranges) in enumerate(partitions)
        ]


    def query(self, session):
        limit = ' limit %s' % self._limit if self._limit else ''
        query = '''
            select {select}
            from {keyspace}.{table}
            where {where}{limit}
        '''.format(
            select=self._select,
            keyspace=self.keyspace,
            table=self.table,
            where=self._where,
            limit=limit
        )
        return session.prepare(query)


class CassandraScanPartition(Partition):
    def __init__(self, dset, part_idx, replicas, token_ranges):
        super().__init__(dset, part_idx)
        self.replicas = replicas
        self.token_ranges = token_ranges


    def _materialize(self, ctx):
        with ctx.cassandra_session(contact_points=self.dset.contact_points) as session:
            session.row_factory = named_tuple_factory
            # session.default_fetch_size = 1000
            # session.client_protocol_handler = NumpyProtocolHandler
            session.row_factory = self.dset._row_factory
            query = self.dset.query(session)
            logger.info('scanning %s token ranges with query %s', len(self.token_ranges), query.query_string.replace('\n', ''))

            results = execute_concurrent_with_args(session, query, self.token_ranges, concurrency=self.dset.concurrency)
            for success, rows in results:
                assert success  # TODO handle failure
                yield from rows


    def preferred_workers(self, workers):
        return [
            worker
            for worker in workers
            for replica in self.replicas
            if replica.address in worker.ip_addresses
        ]
