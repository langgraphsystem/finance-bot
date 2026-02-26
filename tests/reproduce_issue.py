
from src.proactivity.engine import _format_task_deadline


def test_format_task_deadline_ru():
    data = {
        "tasks": [
            {"title": "test task", "due_at": "2026-02-25T06:00:00"}
        ]
    }
    result = _format_task_deadline(data, "ru")
    assert "Ближайшие дедлайны:" in result
    assert "до 2026-02-25T06:00" in result
    assert "Перенести что-нибудь?" in result

def test_format_task_deadline_en():
    data = {
        "tasks": [
            {"title": "test task", "due_at": "2026-02-25T06:00:00"}
        ]
    }
    result = _format_task_deadline(data, "en")
    assert "Upcoming deadlines:" in result
    assert "due 2026-02-25T06:00" in result
    assert "Want me to reschedule any of these?" in result
