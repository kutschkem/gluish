# coding: utf-8
"""
Common tests.
"""

# pylint:disable=F0401,C0111,W0232,E1101,E1103,W0613
from gluish import GLUISH_DATA
from gluish.common import (LineCount, Executable, SplitFile, OAIHarvestChunk,
                           FTPMirror, FTPFile, Directory, FXRates)
from gluish.esindex import CopyToIndex
from gluish.format import TSV
from gluish.path import unlink, wc
from gluish.task import BaseTask
from gluish.utils import random_string
import BeautifulSoup
import datetime
import decimal
import elasticsearch
import luigi
import os
import tempfile
import time
import unittest


# path to fixtures
FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')

# do not send any warning mail
def mock_send_email(subject, message, sender, recipients, image_png=None):
    pass
luigi.notifications.send_email = mock_send_email

# if GLUISH_DATA is set on the system, use it to avoid 'cross-device links'
tempfile.tempdir = os.environ.get(GLUISH_DATA, tempfile.gettempdir())


class TestTask(BaseTask):
    BASE = os.environ.get(GLUISH_DATA, tempfile.gettempdir())
    TAG = 't'


class External(TestTask, luigi.ExternalTask):
    filename = luigi.Parameter(default='l-1.txt')
    def output(self):
        return luigi.LocalTarget(path=os.path.join(FIXTURES, self.filename))


class ConcreteLineCount(TestTask, LineCount):
    filename = luigi.Parameter(default='l-1.txt')
    def requires(self):
        return External(filename=self.filename)

    def output(self):
        return luigi.LocalTarget(path=self.path())


class LineCountTest(unittest.TestCase):

    def test_run_l1(self):
        task = ConcreteLineCount(filename='l-1.txt')
        unlink(task.output().path)
        luigi.build([task], local_scheduler=True)
        content = task.output().open().read().strip()
        self.assertEquals('1', content)

    def test_run_l100(self):
        task = ConcreteLineCount(filename='l-100.txt')
        unlink(task.output().path)
        luigi.build([task], local_scheduler=True)
        content = task.output().open().read().strip()
        self.assertEquals('100', content)


class ExecutableTest(unittest.TestCase):

    def test_executable(self):
        task = Executable(name='ls')
        self.assertTrue(task.complete())

        task = Executable(name='veryunlikely123')
        self.assertFalse(task.complete())


class SplitFileTest(unittest.TestCase):

    def test_split_file(self):
        original = os.path.join(FIXTURES, 'l-100.txt')
        task = SplitFile(filename=original, chunks=10)
        unlink(task.output().path)

        luigi.build([task], local_scheduler=True)
        lines = [line.strip() for line in task.output().open()]
        self.assertEquals(10, len(lines))

        content = ''.join(open(fn).read() for fn in lines)
        with open(original) as handle:
            self.assertEquals(content, handle.read())


class SampleHarvestChunk(OAIHarvestChunk):
    """ Example harvesting. Will go out to the real server. """
    url = luigi.Parameter(default="http://services.dnb.de/oai/repository")
    begin = luigi.DateParameter(default=datetime.date(2011, 1, 1))
    end = luigi.DateParameter(default=datetime.date(2011, 2, 1))
    prefix = luigi.Parameter(default="oai_dc")
    collection = luigi.Parameter(default="dnb:online:dissertations")

    def output(self):
        return luigi.LocalTarget(path=self.path())


class OAIHarvestChunkTest(unittest.TestCase):
    def test_harvest(self):
        task = SampleHarvestChunk()
        luigi.build([task], local_scheduler=True)
        want_path = os.path.join(FIXTURES, 'sample_dnb_oai_response.xml')
        want = BeautifulSoup.BeautifulStoneSoup(open(want_path).read())
        got = BeautifulSoup.BeautifulStoneSoup(task.output().open().read())
        _, temp = tempfile.mkstemp()
        task.output().copy(temp)
        self.assertEquals(want.prettify(), got.prettify(), msg='diff '
                          '{} {}'.format(want_path, temp))


class MirrorTask(TestTask):
    """ Indicator make this task run on each test run. """
    indicator = luigi.Parameter(default=random_string())

    def requires(self):
        return FTPMirror(host='ftp.cs.brown.edu',
            username='anonymous',
            password='anonymous',
            pattern='*02*pdf',
            base='/pub/techreports/00')

    def run(self):
        self.input().move(self.output().path)

    def output(self):
        return luigi.LocalTarget(path=self.path())


class FTPMirrorTest(unittest.TestCase):
    def test_ftp_mirror(self):
        task = MirrorTask()
        luigi.build([task], local_scheduler=True)
        got = task.output().open().read()
        self.assertTrue('cs00-02.pdf' in got,
                        msg='Task output was:\n%s' % got)


class FTPFileCopyTask(TestTask):
    """ Indicator make this task run on each test run. """
    indicator = luigi.Parameter(default=random_string())

    def requires(self):
        return FTPFile(host='ftp.cs.brown.edu',
            username='anonymous',
            password='anonymous',
            filepath='/pub/techreports/00/cs00-07.pdf')

    def run(self):
        self.input().move(self.output().path)

    def output(self):
        return luigi.LocalTarget(path=self.path(ext='pdf'))


class FTPFileCopyTaskWithWrongUsername(TestTask):
    """ Indicator make this task run on each test run. """
    indicator = luigi.Parameter(default=random_string())

    def requires(self):
        return FTPFile(host='ftp.cs.brown.edu',
            username='wrongname',
            password='anonymous',
            filepath='/pub/techreports/00/cs00-07.pdf')

    def run(self):
        self.input().move(self.output().path)

    def output(self):
        return luigi.LocalTarget(path=self.path(ext='pdf'))


class FTPFileTest(unittest.TestCase):
    def test_ftp_file(self):
        task = FTPFileCopyTask()
        luigi.build([task], local_scheduler=True)
        got = task.output().open().read()
        self.assertEquals(216449, len(got))

    def test_ftp_file_with_wrong_username(self):
        task = FTPFileCopyTaskWithWrongUsername()
        luigi.build([task], local_scheduler=True)
        self.assertFalse(task.complete())
        # got = task.output().open().read()
        # self.assertEquals(216449, len(got))


class DirectoryTest(unittest.TestCase):
    def test_create_dir(self):
        target = os.path.join(tempfile.gettempdir(), random_string())
        task = Directory(path=target)
        luigi.build([task], local_scheduler=True)
        self.assertEquals(task.output().path, target)
        self.assertTrue(os.path.isdir(task.output().path))

        # task must be idempotent
        task = Directory(path=target)
        self.assertTrue(task.complete())
        luigi.build([task], local_scheduler=True)
        self.assertEquals(task.output().path, target)
        self.assertTrue(os.path.isdir(task.output().path))


class ECBFXTest(unittest.TestCase):

    EXPECTED_CURRENCIES = set(('AUD', 'BGN', 'BRL', 'CAD', 'CHF', 'CNY', 'CZK',
                               'DKK', 'GBP', 'HKD', 'HRK', 'HUF', 'IDR', 'ILS',
                               'INR', 'JPY', 'KRW', 'MXN', 'MYR', 'NOK', 'NZD',
                               'PHP', 'PLN', 'RON', 'RUB', 'SEK', 'SGD', 'THB',
                               'TRY', 'USD', 'ZAR'))

    def test_fx(self):
        task = FXRates()
        luigi.build([task], local_scheduler=True)
        self.assertEquals(wc(task.output().path), len(ECBFXTest.EXPECTED_CURRENCIES))
        with task.output().open() as handle:
            for row in handle.iter_tsv(cols=('symbol', 'rate')):
                self.assertTrue(row.symbol in ECBFXTest.EXPECTED_CURRENCIES)
                try:
                    decimal.Decimal(row.rate)
                except decimal.InvalidOperation as err:
                    self.fail(err)
