"""Tests for main module."""

from f8a_report.main import time_to_generate_monthly_report


class TodayMockClass:
    """Mock class for `today` from datetime module."""

    def __init__(self, day):
        """Construct the class and initialize day attribute."""
        self.day = day


def test_time_to_generate_monthly_report():
    """Test the function time_to_generate_monthly_report."""
    today = TodayMockClass(1)
    assert time_to_generate_monthly_report(today) is True

    today = TodayMockClass(30)
    assert time_to_generate_monthly_report(today) is False
