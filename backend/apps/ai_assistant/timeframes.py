"""Authoritative relative-date interpretation in the active Django/branch timezone.

The LLM must not invent calendar dates. The resolved window is applied by the
orchestrator to every date-filtered business tool invocation.
"""
import re
from dataclasses import dataclass
from datetime import date, timedelta
from django.utils import timezone


@dataclass(frozen=True)
class TimeWindow:
    start: date
    end: date
    label: str
    explicit: bool = False

    def public(self):
        return {'date_from': self.start.isoformat(), 'date_to': self.end.isoformat(),
                'label': self.label, 'timezone': str(timezone.get_current_timezone()),
                'source': 'django_calendar' if self.explicit else 'default_or_conversation'}


def resolve_window(text, *, today=None, previous=None):
    today = today or timezone.localdate()
    q = ' '.join(text.casefold().split())
    monday = today - timedelta(days=today.weekday())
    if re.search(r'\bday before yesterday\b', q):
        d = today-timedelta(days=2)
        return TimeWindow(d, d, 'day before yesterday', True)
    if re.search(r'\b(?:yesterday|yesteray|yestarday|yesturday)\b', q):
        d = today-timedelta(days=1)
        return TimeWindow(d, d, 'yesterday', True)
    if re.search(r'\btoday\b', q):
        return TimeWindow(today, today, 'today', True)
    numbers = {word: value for value, word in enumerate((
        'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen '
        'sixteen seventeen eighteen nineteen twenty').split()) if value > 0}
    numbers['couple'] = 2
    match = re.search(r'\b(?:last|past|previous)\s+(\d{1,3}|' + '|'.join(numbers) + r')\s+(?:of\s+)?days?\b', q)
    if match:
        n = int(match.group(1)) if match.group(1).isdigit() else numbers[match.group(1)]
        if not 1 <= n <= 366:
            raise ValueError('Requested date window exceeds 366 days.')
        # "past 4 days" includes the current calendar day. "previous 4 full days" does not.
        ends_yesterday = bool(re.search(r'\b(?:full|complete|excluding today)\b', q))
        end = today-timedelta(days=1) if ends_yesterday else today
        return TimeWindow(end-timedelta(days=n-1), end, f'past {n} days', True)
    if 'last week' in q or 'previous week' in q:
        return TimeWindow(monday-timedelta(days=7), monday-timedelta(days=1), 'last week', True)
    if 'this week' in q or 'current week' in q:
        return TimeWindow(monday, today, 'this week', True)
    if 'last month' in q or 'previous month' in q:
        end = today.replace(day=1)-timedelta(days=1)
        return TimeWindow(end.replace(day=1), end, 'last month', True)
    if 'this month' in q or 'current month' in q:
        return TimeWindow(today.replace(day=1), today, 'this month', True)
    dates = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', q)
    if dates:
        parsed = [date.fromisoformat(x) for x in dates[:2]]
        start, end = (parsed[0], parsed[-1])
        if end < start or (end-start).days > 365:
            raise ValueError('Date range must be ordered and at most 366 days.')
        return TimeWindow(start, end, 'explicit dates', True)
    if previous and isinstance(previous, dict):
        last = previous.get('time_window')
        if isinstance(last, dict):
            try:
                start, end = date.fromisoformat(last['date_from']), date.fromisoformat(last['date_to'])
                if start <= end and (end-start).days <= 365:
                    return TimeWindow(start, end, 'conversation follow-up')
            except (TypeError, ValueError, KeyError):
                pass
    return TimeWindow(today-timedelta(days=29), today, 'last 30 days (default)')
