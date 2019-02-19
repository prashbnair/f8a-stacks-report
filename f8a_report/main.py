"""Entry file for the main functionality."""

from datetime import datetime as dt, timedelta, date
from report_helper import ReportHelper


def main():
    """Generate the weekly and monthly stacks report."""
    r = ReportHelper()

    today = dt.today()

    start_date = (today - timedelta(days=7)).strftime('%Y-%m-%d')
    end_date = (today - timedelta(days=1)).strftime('%Y-%m-%d')
    weekly_response = r.get_report(start_date, end_date, 'weekly')

    if today.day in (1, 2, 3, 4, 5, 6, 7):
        last_day_of_prev_month = date(today.year, today.month, 1) - timedelta(days=1)
        last_month_first_date = last_day_of_prev_month.strftime('%Y-%m-01')
        last_month_end_date = last_day_of_prev_month.strftime('%Y-%m-%d')
        monthly_response = r.get_report(last_month_first_date, last_month_end_date, 'monthly')


if __name__ == '__main__':
    main()
