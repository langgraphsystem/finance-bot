"""Tests for chart generation."""

from src.core.charts import create_pie_chart, create_bar_chart, create_line_chart


def test_pie_chart_returns_url():
    """Pie chart should return a QuickChart URL."""
    url = create_pie_chart(["Food", "Transport"], [100, 50], "Expenses")
    assert url.startswith("https://quickchart.io")
    assert "pie" in url or "chart" in url


def test_pie_chart_no_title():
    """Pie chart without title should still work."""
    url = create_pie_chart(["A", "B"], [10, 20])
    assert url.startswith("https://quickchart.io")


def test_bar_chart_returns_url():
    """Bar chart should return a QuickChart URL."""
    url = create_bar_chart(["Jan", "Feb"], [100, 200], "Monthly")
    assert url.startswith("https://quickchart.io")


def test_bar_chart_no_title():
    """Bar chart without title should still work."""
    url = create_bar_chart(["A", "B"], [10, 20])
    assert url.startswith("https://quickchart.io")


def test_line_chart_returns_url():
    """Line chart should return a QuickChart URL."""
    datasets = [
        {"label": "Income", "data": [100, 200], "borderColor": "#36A2EB"},
        {"label": "Expenses", "data": [80, 150], "borderColor": "#FF6384"},
    ]
    url = create_line_chart(["Jan", "Feb"], datasets, "Trend")
    assert url.startswith("https://quickchart.io")


def test_line_chart_no_title():
    """Line chart without title should still work."""
    datasets = [{"label": "Data", "data": [1, 2, 3]}]
    url = create_line_chart(["A", "B", "C"], datasets)
    assert url.startswith("https://quickchart.io")


def test_pie_chart_custom_dimensions():
    """Pie chart should accept custom width/height."""
    url = create_pie_chart(["A"], [10], "Test", width=800, height=600)
    assert url.startswith("https://quickchart.io")
