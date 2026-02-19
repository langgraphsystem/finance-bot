from src.skills.add_contact.handler import skill as add_contact_skill
from src.skills.add_expense.handler import skill as add_expense_skill
from src.skills.add_income.handler import skill as add_income_skill
from src.skills.add_recurring.handler import skill as add_recurring_skill
from src.skills.base import SkillRegistry
from src.skills.cancel_booking.handler import skill as cancel_booking_skill
from src.skills.compare_options.handler import skill as compare_options_skill
from src.skills.complete_task.handler import skill as complete_task_skill
from src.skills.complex_query.handler import skill as complex_query_skill
from src.skills.correct_category.handler import skill as correct_category_skill
from src.skills.create_booking.handler import skill as create_booking_skill
from src.skills.create_event.handler import skill as create_event_skill
from src.skills.create_task.handler import skill as create_task_skill
from src.skills.day_plan.handler import skill as day_plan_skill
from src.skills.day_reflection.handler import skill as day_reflection_skill
from src.skills.draft_message.handler import skill as draft_message_skill
from src.skills.draft_reply.handler import skill as draft_reply_skill
from src.skills.evening_recap.handler import skill as evening_recap_skill
from src.skills.find_contact.handler import skill as find_contact_skill
from src.skills.find_free_slots.handler import skill as find_free_slots_skill
from src.skills.follow_up_email.handler import skill as follow_up_email_skill
from src.skills.general_chat.handler import skill as general_chat_skill
from src.skills.life_search.handler import skill as life_search_skill
from src.skills.list_bookings.handler import skill as list_bookings_skill
from src.skills.list_contacts.handler import skill as list_contacts_skill
from src.skills.list_events.handler import skill as list_events_skill
from src.skills.list_tasks.handler import skill as list_tasks_skill
from src.skills.mark_paid.handler import skill as mark_paid_skill
from src.skills.mood_checkin.handler import skill as mood_checkin_skill
from src.skills.morning_brief.handler import skill as morning_brief_skill

# Phase 5: Monitor & browser skills
from src.skills.news_monitor.handler import skill as news_monitor_skill
from src.skills.onboarding.handler import skill as onboarding_skill
from src.skills.price_alert.handler import skill as price_alert_skill
from src.skills.price_check.handler import skill as price_check_skill
from src.skills.proofread.handler import skill as proofread_skill
from src.skills.query_report.handler import skill as query_report_skill
from src.skills.query_stats.handler import skill as query_stats_skill
from src.skills.quick_answer.handler import skill as quick_answer_skill
from src.skills.quick_capture.handler import skill as quick_capture_skill
from src.skills.read_inbox.handler import skill as read_inbox_skill
from src.skills.reschedule_booking.handler import skill as reschedule_booking_skill
from src.skills.reschedule_event.handler import skill as reschedule_event_skill
from src.skills.scan_document.handler import skill as scan_document_skill
from src.skills.scan_receipt.handler import skill as scan_receipt_skill
from src.skills.send_email.handler import skill as send_email_skill
from src.skills.send_to_client.handler import skill as send_to_client_skill
from src.skills.set_budget.handler import skill as set_budget_skill
from src.skills.set_comm_mode.handler import skill as set_comm_mode_skill
from src.skills.set_reminder.handler import skill as set_reminder_skill
from src.skills.shopping_list.handler import (
    shopping_list_add_skill,
    shopping_list_clear_skill,
    shopping_list_remove_skill,
    shopping_list_view_skill,
)
from src.skills.summarize_thread.handler import skill as summarize_thread_skill
from src.skills.track_drink.handler import skill as track_drink_skill
from src.skills.track_food.handler import skill as track_food_skill
from src.skills.translate_text.handler import skill as translate_text_skill
from src.skills.undo_last.handler import skill as undo_last_skill
from src.skills.web_action.handler import skill as web_action_skill
from src.skills.web_search.handler import skill as web_search_skill
from src.skills.write_post.handler import skill as write_post_skill


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
    registry.register(create_task_skill)
    registry.register(list_tasks_skill)
    registry.register(set_reminder_skill)
    registry.register(complete_task_skill)
    registry.register(quick_answer_skill)
    registry.register(web_search_skill)
    registry.register(compare_options_skill)
    registry.register(draft_message_skill)
    registry.register(translate_text_skill)
    registry.register(write_post_skill)
    registry.register(proofread_skill)
    registry.register(read_inbox_skill)
    registry.register(send_email_skill)
    registry.register(draft_reply_skill)
    registry.register(follow_up_email_skill)
    registry.register(summarize_thread_skill)
    registry.register(list_events_skill)
    registry.register(create_event_skill)
    registry.register(find_free_slots_skill)
    registry.register(reschedule_event_skill)
    registry.register(morning_brief_skill)
    registry.register(shopping_list_add_skill)
    registry.register(shopping_list_view_skill)
    registry.register(shopping_list_remove_skill)
    registry.register(shopping_list_clear_skill)
    registry.register(evening_recap_skill)
    # Phase 5: Browser + monitor skills
    registry.register(web_action_skill)
    registry.register(price_check_skill)
    registry.register(price_alert_skill)
    registry.register(news_monitor_skill)
    # Phase 6: Booking + CRM skills
    registry.register(add_contact_skill)
    registry.register(list_contacts_skill)
    registry.register(find_contact_skill)
    registry.register(create_booking_skill)
    registry.register(list_bookings_skill)
    registry.register(cancel_booking_skill)
    registry.register(reschedule_booking_skill)
    registry.register(send_to_client_skill)
    return registry
