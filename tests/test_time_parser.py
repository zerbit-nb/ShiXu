from datetime import datetime

import pytest

from app.services.time_parser import parse_deadline


@pytest.mark.parametrize('text, reference, expected', [
    ('明天 20:00 前', '2026-12-31T12:00:00+08:00', '2027-01-01T20:00:00+08:00'),
    ('本周五 20:00', '2026-10-10T12:00:00+08:00', '2026-10-09T20:00:00+08:00'),
    ('下周一', '2026-10-11T12:00:00+08:00', '2026-10-12'),
    ('2026年10月12日', None, '2026-10-12'),
    ('2026-10-12 8:30', None, '2026-10-12T08:30:00+08:00'),
    ('10月12日', None, None),
    ('明天', None, None),
    ('周五', '2026-10-10T12:00:00+08:00', None),
    ('2026年2月30日', None, None),
    ('10月12日', '2026-10-10T12:00:00+08:00', None),
    ('2026年10月12日或2026年10月14日', None, None),
    ('尽快', '2026-10-10T12:00:00+08:00', None),
])
def test_deadline_does_not_invent_precision_or_reference(text, reference, expected):
    result = parse_deadline(text, datetime.fromisoformat(reference) if reference else None)
    assert result['deadline'] == expected
    if expected is None:
        assert result['warning']


def test_no_deadline_is_not_an_error():
    assert parse_deadline(None, None) == {'deadline': None, 'warning': None}
