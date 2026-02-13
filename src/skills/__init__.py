from src.skills.add_expense.handler import skill as add_expense_skill
from src.skills.add_income.handler import skill as add_income_skill
from src.skills.add_recurring.handler import skill as add_recurring_skill
from src.skills.base import SkillRegistry
from src.skills.complex_query.handler import skill as complex_query_skill
from src.skills.correct_category.handler import skill as correct_category_skill
from src.skills.general_chat.handler import skill as general_chat_skill
from src.skills.mark_paid.handler import skill as mark_paid_skill
from src.skills.onboarding.handler import skill as onboarding_skill
from src.skills.query_report.handler import skill as query_report_skill
from src.skills.query_stats.handler import skill as query_stats_skill
from src.skills.scan_receipt.handler import skill as scan_receipt_skill
from src.skills.set_budget.handler import skill as set_budget_skill
from src.skills.undo_last.handler import skill as undo_last_skill


def create_registry() -> SkillRegistry:
    """Create and populate the skill registry."""
    registry = SkillRegistry()
    registry.register(onboarding_skill)
    registry.register(add_expense_skill)
    registry.register(add_income_skill)
    registry.register(scan_receipt_skill)
    registry.register(query_stats_skill)
    registry.register(general_chat_skill)
    registry.register(correct_category_skill)
    registry.register(undo_last_skill)
    registry.register(query_report_skill)
    registry.register(set_budget_skill)
    registry.register(mark_paid_skill)
    registry.register(add_recurring_skill)
    registry.register(complex_query_skill)
    return registry
