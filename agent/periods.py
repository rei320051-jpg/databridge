"""Deterministic date interpretation against the shared dataset reference day."""
import calendar
import re
from datetime import date, timedelta

from shared.contracts import REFERENCE_DATE

CN_MONTH = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7,
            '八': 8, '九': 9, '十': 10, '十一': 11, '十二': 12}


class UnsupportedPeriod(ValueError):
    """A multi-period request cannot be represented by the frozen gateway plan."""


def month_bounds(year, month):
    return date(year, month, 1).isoformat(), date(year, month, calendar.monthrange(year, month)[1]).isoformat()


def parse_period(question):
    anchor = date.fromisoformat(REFERENCE_DATE)
    # Full day ranges must precede single-day recognition. The right year and
    # month can be omitted only when inherited from an explicit left date.
    iso = re.search(r'(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\s*(?:至|到|~|—)\s*(20\d{2})[-/](\d{1,2})[-/](\d{1,2})', question)
    chinese = re.search(r'(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})[日号]\s*(?:至|到|~|—|-)\s*(?:(20\d{2})年)?(?:(\d{1,2})月)?(\d{1,2})[日号]', question)
    if iso or chinese:
        y1, m1, d1, y2, m2, d2 = (iso or chinese).groups()
        start = date(int(y1 or anchor.year), int(m1), int(d1))
        end = date(int(y2 or start.year), int(m2 or start.month), int(d2))
        if start > end:
            raise ValueError('开始日期不能晚于结束日期')
        return start.isoformat(), end.isoformat()
    days = re.findall(r'(20\d{2})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})', question)
    partial = re.findall(r'(\d{1,2})月(\d{1,2})[日号]', question)
    if len(days) > 1 or len(partial) > 1:
        raise UnsupportedPeriod('多个日期应分别查询，不能只执行第一天')
    if days:
        day = date(*map(int, days[0])).isoformat()
        return day, day
    if partial:
        day = date(anchor.year, *map(int, partial[0])).isoformat()
        return day, day
    span = re.search(r'(?:(20\d{2})年)?(\d{1,2})月\s*(?:到|至|[-~—])\s*(?:(20\d{2})年)?(\d{1,2})月', question)
    if span:
        y1, m1, y2, m2 = span.groups()
        y1, y2 = int(y1 or y2 or anchor.year), int(y2 or y1 or anchor.year)
        start, end = month_bounds(y1, int(m1))[0], month_bounds(y2, int(m2))[1]
        if start > end:
            raise ValueError('开始月份不能晚于结束月份')
        return start, end
    if len(re.findall(r'(?:\d{1,2}|[一二三四五六七八九十]{1,2})月', question)) > 1:
        raise UnsupportedPeriod('多个期间应分别查询，或使用完整自然月环比')
    quarter = re.search(r'(?:(20\d{2})年)?第?([一二三四1234])季度', question)
    if quarter:
        q = {'一': 1, '二': 2, '三': 3, '四': 4}.get(quarter[2], quarter[2])
        first = (int(q) - 1) * 3 + 1
        year = int(quarter[1] or anchor.year)
        return month_bounds(year, first)[0], month_bounds(year, first + 2)[1]
    for term, offset in [('前天', 2), ('昨天', 1), ('今天', 0)]:
        if term in question:
            day = (anchor - timedelta(days=offset)).isoformat()
            return day, day
    month = re.search(r'(?:(20\d{2})年)?(\d{1,2})月', question)
    if month:
        return month_bounds(int(month[1] or anchor.year), int(month[2]))
    chinese_month = re.search(r'(?:(20\d{2})年)?([一二三四五六七八九十]{1,2})月', question)
    if chinese_month and chinese_month[2] in CN_MONTH:
        return month_bounds(int(chinese_month[1] or anchor.year), CN_MONTH[chinese_month[2]])
    if '本月' in question or '这个月' in question:
        return month_bounds(anchor.year, anchor.month)
    if '上个月' in question or '上月' in question:
        prior = anchor.replace(day=1) - timedelta(days=1)
        return month_bounds(prior.year, prior.month)
    recent = re.search(r'(?:近|最近|过去)(\d+)天', question)
    if recent:
        count = int(recent[1])
        if not 1 <= count <= 366:
            raise ValueError('最近天数必须为 1 至 366')
        return (anchor - timedelta(days=count - 1)).isoformat(), anchor.isoformat()
    return None, None
