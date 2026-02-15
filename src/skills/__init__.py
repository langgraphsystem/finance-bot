from src.skills.add_expense.handler import skill as add_expense_skill
from src.skills.add_income.handler import skill as add_income_skill
from src.skills.add_recurring.handler import skill as add_recurring_skill
from src.skills.base import SkillRegistry
from src.skills.complex_query.handler import skill as complex_query_skill
from src.skills.correct_category.handler import skill as correct_category_skill
from src.skills.day_plan.handler import skill as day_plan_skill
from src.skills.day_reflection.handler import skill as day_reflection_skill
from src.skills.general_chat.handler import skill as general_chat_skill
from src.skills.life_search.handler import skill as life_search_skill
from src.skills.mark_paid.handler import skill as mark_paid_skill
from src.skills.mood_checkin.handler import skill as mood_checkin_skill
from src.skills.onboarding.handler import skill as onboarding_skill
from src.skills.query_report.handler import skill as query_report_skill
from src.skills.query_stats.handler import skill as query_stats_skill
from src.skills.quick_capture.handler import skill as quick_capture_skill
from src.skills.scan_document.handler import skill as scan_document_skill
from src.skills.scan_receipt.handler import skill as scan_receipt_skill
from src.skills.set_budget.handler import skill as set_budget_skill
from src.skills.set_comm_mode.handler import skill as set_comm_mode_skill
from src.skills.track_drink.handler import skill as track_drink_skill
from src.skills.track_food.handler import skill as track_food_skill
from src.skills.undo_last.handler import skill as undo_last_skill


def create_registry() -> SkillRegistry:
    """Create and populate the skill registry."""
    registry = SkillRegistry()
    registry.register(onboarding_skill)
    registry.register(add_expense_skill)
    registry.register(add_income_skill)
    registry.register(scan_receipt_skill)
    registry.register(scan_document_skill)
    registry.register(query_stats_skill)
    registry.register(general_chat_skill)
    registry.register(correct_category_skill)
    registry.register(undo_last_skill)
    registry.register(query_report_skill)
    registry.register(set_budget_skill)
    registry.register(mark_paid_skill)
    registry.register(add_recurring_skill)
    registry.register(complex_query_skill)
    registry.register(quick_capture_skill)
    registry.register(track_food_skill)
    registry.register(track_drink_skill)
    registry.register(mood_checkin_skill)
    registry.register(day_plan_skill)
    registry.register(day_reflection_skill)
    registry.register(life_search_skill)
    registry.register(set_comm_mode_skill)
    return registry
