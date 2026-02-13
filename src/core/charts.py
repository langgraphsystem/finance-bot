"""QuickChart wrapper for generating chart images."""

from quickchart import QuickChart


def create_pie_chart(
    labels: list[str],
    values: list[float],
    title: str = "",
    width: int = 500,
    height: int = 400,
) -> str:
    """Create a pie chart and return its URL."""
    qc = QuickChart()
    qc.width = width
    qc.height = height
    qc.config = {
        "type": "pie",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "data": values,
                    "backgroundColor": [
                        "#FF6384",
                        "#36A2EB",
                        "#FFCE56",
                        "#4BC0C0",
                        "#9966FF",
                        "#FF9F40",
                        "#C9CBCF",
                        "#7BC8A4",
                        "#E7E9ED",
                        "#FF99CC",
                    ],
                }
            ],
        },
        "options": {
            "title": {"display": bool(title), "text": title},
            "plugins": {
                "datalabels": {
                    "display": True,
                    "formatter": "(val) => '$' + val",
                },
            },
        },
    }
    return qc.get_url()


def create_bar_chart(
    labels: list[str],
    values: list[float],
    title: str = "",
    width: int = 500,
    height: int = 400,
) -> str:
    """Create a bar chart and return its URL."""
    qc = QuickChart()
    qc.width = width
    qc.height = height
    qc.config = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": title,
                    "data": values,
                    "backgroundColor": "#36A2EB",
                }
            ],
        },
        "options": {
            "title": {"display": bool(title), "text": title},
        },
    }
    return qc.get_url()


def create_line_chart(
    labels: list[str],
    datasets: list[dict],
    title: str = "",
    width: int = 600,
    height: int = 400,
) -> str:
    """Create a line chart and return its URL."""
    qc = QuickChart()
    qc.width = width
    qc.height = height
    qc.config = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": datasets,
        },
        "options": {
            "title": {"display": bool(title), "text": title},
        },
    }
    return qc.get_url()
