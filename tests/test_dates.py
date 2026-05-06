from datetime import datetime

from app.utils.dates import start_of_day, start_of_month, start_of_week


def test_start_of_day():
    moment = datetime(2024, 5, 10, 15, 30)
    assert start_of_day(moment) == datetime(2024, 5, 10)


def test_start_of_week():
    moment = datetime(2024, 5, 10)  # Friday
    assert start_of_week(moment) == datetime(2024, 5, 6)  # Monday


def test_start_of_month():
    moment = datetime(2024, 5, 25)
    assert start_of_month(moment) == datetime(2024, 5, 1)