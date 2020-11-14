import re

from dateutil import parser
from datetime import datetime, timedelta
from pytz import timezone

WEEKDAYS = [
    'Monday',
    'Tuesday',
    'Wednesday',
    'Thursday',
    'Friday',
    'Saturday',
    'Sunday',
]


def amount_to_string(x):
    return '${:.2f}'.format(x / 100)


def snake_case(x):
    return re.sub(r'(?<!^)(?=[A-Z])', '_', x).lower()


def mixed_case(x):
    return ''.join(y.title() if i else y for i, y in enumerate(x.split('_')))


def first_item(x, depth=1):
    return x[sorted(x.keys())[0]] if depth == 1 else first_item(x[sorted(
        x.keys())[0]])


def localtime(initial=None):
    if type(initial) == str:
        return parser.parse(initial).astimezone(timezone('America/Denver'))
    elif type(initial) == datetime:
        return datetime.astimezone(timezone('America/Denver'))
    return datetime.now(timezone('America/Denver'))


def epoch_start(weekday, time, offset=0):
    return (time - timedelta(
        days=(
            (time.weekday() - WEEKDAYS.index(weekday)) %
            len(WEEKDAYS)) - offset * len(WEEKDAYS))).replace(
                hour=0,
                second=0,
                microsecond=0,
            )
