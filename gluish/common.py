# coding: utf-8

"""
Tasks that can be used out of the box.
"""
# pylint: disable=F0401,W0232,R0903,E1101
from gluish.benchmark import timed
from gluish.format import TSV
from gluish.oai import oai_harvest
from gluish.path import iterfiles, which
from gluish.task import BaseTask
from gluish.utils import shellout, random_string
import BeautifulSoup
import datetime
import collections
import elasticsearch
import json
import luigi
import os
import tempfile


class CommonTask(BaseTask):
    """
    A base class for common classes. These artefacts will be written to the
    systems tempdir.
    """
    BASE = tempfile.gettempdir()
    TAG = 'common'


class Indices(luigi.Task):
    """
    List all ES indices and doc counts.
    """
    host = luigi.Parameter(default='localhost')
    port = luigi.IntParameter(default=9200)

    @timed
    def run(self):
        """ Write info about indices to stdout. """
        es = elasticsearch.Elasticsearch([{'host': self.host,
                                           'port': self.port}])
        stats = es.indices.stats()
        indices = collections.Counter()
        for key, value in stats.get('indices').iteritems():
            indices[key] = value.get('primaries').get('docs').get('count')
        total = sum(indices.values())
        print(json.dumps(dict(indices=indices, total=total,
                              sources=len(indices)), indent=4))

    def complete(self):
        return False


class SplitFile(CommonTask):
    """
    Idempotent wrapper around split -l.
    Given a filename and the number of chunks, the output of this task is
    a single file, which contains the paths to the chunk files, one per line.
    """
    filename = luigi.Parameter()
    chunks = luigi.IntParameter(default=1)

    def run(self):
        line_count = sum(1 for line in open(self.filename))
        lines = int((line_count + self.chunks) / self.chunks)

        taskdir = os.path.dirname(self.output().fn)
        if not os.path.exists(taskdir):
            os.makedirs(taskdir)

        prefix = random_string()
        shellout("cd {taskdir} && split -l {lines} {input} {prefix}",
                 taskdir=taskdir, lines=lines, input=self.filename,
                 prefix=prefix)

        with self.output().open('w') as output:
            for path in sorted(iterfiles(taskdir)):
                if os.path.basename(path).startswith(prefix):
                    output.write_tsv(path)

    def output(self):
        return luigi.LocalTarget(path=self.path(digest=True), format=TSV)


class Executable(luigi.Task):
    """
    Checks, whether an external executable is available. This task will consider
    itself complete, only if the executable `name` is found in PATH on the
    system.
    """
    name = luigi.Parameter()
    message = luigi.Parameter(default="")

    def run(self):
        """ Only run if, task is not complete. """
        raise RuntimeError('External app %s required.\n%s' % (self.name,
                           self.message))

    def complete(self):
        return which(self.name) is not None


class LineCount(luigi.Task):
    """ Wrapped wc -l. """
    def requires(self):
        raise NotImplementedError("Should be some file with lines to count.")

    @timed
    def run(self):
        """ wc -l wrapped. """
        tmp = shellout("wc -l < {input} > {output}", input=self.input().fn)
        luigi.File(tmp).move(self.output().fn)

    def output(self):
        raise NotImplementedError()


class OAIHarvestChunk(CommonTask):
    """ Template task to harvest a piece of OAI. """

    begin = luigi.DateParameter(default=datetime.date.today())
    end = luigi.DateParameter(default=datetime.date.today())
    prefix = luigi.Parameter(default="marc21")
    url = luigi.Parameter(default="http://oai.bnf.fr/oai2/OAIHandler")
    collection = luigi.Parameter(default=None)

    def run(self):
        stopover = tempfile.mkdtemp(prefix='gluish-')
        oai_harvest(url=self.url, begin=self.begin, end=self.end,
                    prefix=self.prefix, directory=stopover,
                    collection=self.collection)

        with self.output().open('w') as output:
            output.write("""<collection
                xmlns="http://www.openarchives.org/OAI/2.0/"
                xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            """)
            for path in iterfiles(stopover):
                with open(path) as handle:
                    soup = BeautifulSoup.BeautifulStoneSoup(handle.read())
                    for record in soup.findAll('record'):
                        output.write(str(record)) # or unicode?
            output.write('</collection>\n')

    def output(self):
        raise NotImplementedError()




