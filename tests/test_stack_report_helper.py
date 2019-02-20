"""Tests for classes from stack_report_helper module."""

from f8a_report.report_helper import ReportHelper, S3Helper, Postgres
from pathlib import Path
import pytest
from unittest import mock

r = ReportHelper()


def test_validate_and_process_date_success():
    """Test the success scenario of the function validate_and_process_date."""
    res = r.validate_and_process_date('2019-01-01')
    assert(res == '2019-01-01')


def test_validate_and_process_date_failure():
    """Test the failure scenario of the function validate_and_process_date."""
    with pytest.raises(ValueError) as e:
        r.validate_and_process_date('xyzabc')
        assert str(e.value) == 'Incorrect data format, should be YYYY-MM-DD'


def test_flatten_list():
    """Test the success scenario of the function flatten_list."""
    assert(r.flatten_list([[1, 2], [3, 4]]) == [1, 2, 3, 4])


def test_datediff_in_millisecs():
    """Test the success scenario of the function datediff_in_millisecs."""
    start, end = '2018-08-23T17:05:52.912429', '2018-08-23T17:05:53.624783'
    assert(r.datediff_in_millisecs(start, end) == 712.354)


def test_normalize_deps_list():
    """Test the success scenario of the function normalize_deps_list."""
    deps_list = [{'package': 'abc', 'version': '1.0.0'}]
    assert(r.normalize_deps_list(deps_list) == ['abc 1.0.0'])


def test_populate_key_count_success():
    """Test the success scenario of the function populate_key_count."""
    assert (r.populate_key_count(['abc 1.0.0', 'xyz 1.0.0', 'abc 1.0.0']) ==
            {'abc 1.0.0': 2, 'xyz 1.0.0': 1})


def test_populate_key_count_failure():
    """Test the failure scenario of the function populate_key_count."""
    with pytest.raises(Exception) as e:
        r.populate_key_count([[], {}])
        assert(e.value == 'TypeError("unhashable type: \'list\'",)')


def test_S3helper():
    """Test the failure scenario of the __init__ method of the class S3Helper."""
    s = S3Helper()
    assert(s.s3 is not None)


@mock.patch('f8a_report.report_helper.S3Helper.store_json_content', return_value=True)
def test_normalize_worker_data(_mock_count):
    """Test the success scenario of the function normalize_worker_data."""
    with open('tests/data/stackdata.json', 'r') as f:
        stackdata = f.read()
        resp = r.normalize_worker_data('2018-10-10', '2018-10-18',
                                       stackdata, 'stack_aggregator_v2', 'weekly')

        assert(resp is not None)
