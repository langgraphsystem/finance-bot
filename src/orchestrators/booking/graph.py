"""Booking orchestrator — LangGraph StateGraph for hotel booking FSM.

Replaces the Redis-based FSM in ``src/tools/browser_booking`` with a
LangGraph graph that uses ``interrupt()`` at every user-interaction point.

Graph structure::

    START → parse_request → preview_prices → ask_platform (interrupt)
        → check_auth ─┬─ auth_ok → search_hotels → present_results (interrupt)
                       └─ need_login → ask_login (interrupt) → check_auth
        → [results_ready] → present_results (interrupt)
            → hotel_selected → confirm_selection (interrupt)
                → confirmed → execute_booking → finalize → END
                → back → present_results
            → sort/more → search_hotels
        → finalize → END

Each interrupt() pauses the graph and returns control to the user.
The router resumes with ``Command(resume=choice)`` when the user
clicks a button or sends a text message.
"""

import logging
import uuid
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage
from src.orchestrators.booking.nodes import (
    ask_login,
    ask_platform,
    check_auth,
    confirm_selection,
    execute_booking_node,
    finalize,
    parse_request,
    present_results,
    preview_prices,
    route_after_auth,
    route_after_confirm,
    route_after_login,
    route_after_results,
    search_hotels,
)
from src.orchestrators.booking.state import BookingState
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)


def build_booking_graph() -> StateGraph:
    """Build the hotel booking graph with interrupt-based HITL."""
    graph = StateGraph(BookingState)

    # Nodes
    graph.add_node("parse_request", parse_request)
    graph.add_node("preview_prices", preview_prices)
    graph.add_node("ask_platform", ask_platform)
    graph.add_node("check_auth", check_auth)
    graph.add_node("ask_login", ask_login)
    graph.add_node("search", search_hotels)
    graph.add_node("present_results", present_results)
    graph.add_node("confirm_selection", confirm_selection)
    graph.add_node("execute_booking", execute_booking_node)
    graph.add_node("finalize", finalize)

    # Entry
    graph.add_edge(START, "parse_request")
    graph.add_edge("parse_request", "preview_prices")
    graph.add_edge("preview_prices", "ask_platform")

    # After platform selection → auth check
    graph.add_conditional_edges(
        "ask_platform",
        lambda s: "finalize" if s.get("step") in ("error", "cancelled") else "check_auth",
        {"check_auth": "check_auth", "finalize": "finalize"},
    )

    # Auth check → search or login
    graph.add_conditional_edges("check_auth", route_after_auth, {
        "search": "search",
        "ask_login": "ask_login",
        "finalize": "finalize",
    })

    # After login → re-check auth or cancel
    graph.add_conditional_edges("ask_login", route_after_login, {
        "check_auth": "check_auth",
        "finalize": "finalize",
    })

    # Search → present results
    graph.add_edge("search", "present_results")

    # Results → select, sort, more, cancel
    graph.add_conditional_edges("present_results", route_after_results, {
        "confirm_selection": "confirm_selection",
        "search": "search",
        "finalize": "finalize",
    })

    # Confirm → book, back, cancel
    graph.add_conditional_edges("confirm_selection", route_after_confirm, {
        "execute_booking": "execute_booking",
        "present_results": "present_results",
        "finalize": "finalize",
    })

    # Booking → finalize
    graph.add_edge("execute_booking", "finalize")
    graph.add_edge("finalize", END)

    return graph


_booking_graph = None


def _get_booking_graph():
    """Lazily compile with checkpointer for durable state."""
    global _booking_graph
    if _booking_graph is not None:
        return _booking_graph

    from src.core.config import settings
    from src.orchestrators.checkpointer import get_checkpointer

    builder = build_booking_graph()
    checkpointer = get_checkpointer() if settings.ff_langgraph_checkpointer else None
    _booking_graph = builder.compile(checkpointer=checkpointer)
    return _booking_graph


class BookingOrchestrator:
    """Hotel booking orchestrator — replaces Redis FSM with LangGraph.

    Uses interrupt/resume for multi-step user interaction:
    platform selection, login, hotel selection, confirmation.
    """

    _GRAPH_INTENTS = {"create_booking"}

    def __init__(self, agent_router: Any = None):
        self._agent_router = agent_router

    async def invoke(
        self,
        intent: str,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Start or continue a booking flow."""
        # Only graph-route create_booking when it looks like a hotel request
        if intent == "create_booking" and self._is_hotel_request(
            message.text or "", intent_data
        ):
            return await self._start_booking(message, context, intent_data)

        # All other booking intents → AgentRouter
        if self._agent_router:
            return await self._agent_router.route(
                intent, message, context, intent_data
            )
        return SkillResult(response_text="Booking feature is being set up.")

    async def _start_booking(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Start a new hotel booking graph."""
        thread_id = f"booking-{context.user_id}-{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}

        initial_state: BookingState = {
            "user_id": context.user_id,
            "family_id": context.family_id,
            "language": context.language or "en",
            "task": message.text or "",
            "step": "start",
            "error": "",
            "parsed": {},
            "preview_text": "",
            "site": "",
            "results": [],
            "page": 1,
            "search_url": "",
            "selected_hotel": {},
            "booking_data": {},
            "user_choice": "",
            "response_text": "",
            "buttons": [],
        }

        try:
            result = await _get_booking_graph().ainvoke(initial_state, config)
            return self._build_result(result, thread_id)
        except Exception as e:
            logger.warning("Booking graph failed: %s", e)
            try:
                from src.orchestrators.resilience import save_to_dlq

                await save_to_dlq(
                    graph_name="booking",
                    thread_id=thread_id,
                    user_id=context.user_id,
                    family_id=context.family_id,
                    error=str(e),
                )
            except Exception:
                pass
            if self._agent_router:
                return await self._agent_router.route(
                    "create_booking", message, context, intent_data
                )
            return SkillResult(
                response_text="Couldn't start hotel search. Try again."
            )

    async def resume(self, thread_id: str, choice: str) -> SkillResult:
        """Resume a paused booking graph with the user's choice."""
        from langgraph.types import Command

        config = {"configurable": {"thread_id": thread_id}}
        try:
            result = await _get_booking_graph().ainvoke(
                Command(resume=choice), config
            )
            return self._build_result(result, thread_id)
        except Exception as e:
            logger.error("Booking graph resume failed: %s", e)
            return SkillResult(
                response_text="Error continuing hotel search. Try again."
            )

    def _build_result(
        self, result: dict[str, Any], thread_id: str
    ) -> SkillResult:
        """Build SkillResult from graph result, handling interrupts."""
        interrupts = result.get("__interrupt__", [])
        if interrupts:
            return self._handle_interrupt(interrupts[0], thread_id)

        text = result.get("response_text", "")
        buttons = result.get("buttons", [])
        return SkillResult(response_text=text or "Done.", buttons=buttons or None)

    def _handle_interrupt(
        self, intr: Any, thread_id: str
    ) -> SkillResult:
        """Build SkillResult with buttons for a graph interrupt."""
        data = intr.value if hasattr(intr, "value") else intr
        intr_type = data.get("type", "")

        if intr_type == "platform_selection":
            return self._platform_buttons(data, thread_id)
        if intr_type == "login_required":
            return self._login_buttons(data, thread_id)
        if intr_type == "hotel_selection":
            return self._selection_buttons(data, thread_id)
        if intr_type == "booking_confirmation":
            return self._confirm_buttons(data, thread_id)

        # Generic fallback
        text = data.get("message", data.get("response_text", "Continue?"))
        buttons = [
            {"text": "Continue", "callback": f"graph_resume:{thread_id}:yes"},
            {"text": "Cancel", "callback": f"graph_resume:{thread_id}:cancel"},
        ]
        return SkillResult(response_text=text, buttons=buttons)

    @staticmethod
    def _platform_buttons(
        data: dict, thread_id: str
    ) -> SkillResult:
        platforms = data.get("platforms", [])
        text = data.get("preview_text", "Select a platform:")
        buttons = []
        for p in platforms:
            buttons.append({
                "text": p,
                "callback": f"graph_resume:{thread_id}:{p}",
            })
        buttons.append({
            "text": "Cancel",
            "callback": f"graph_resume:{thread_id}:cancel",
        })
        return SkillResult(response_text=text, buttons=buttons)

    @staticmethod
    def _login_buttons(
        data: dict, thread_id: str
    ) -> SkillResult:
        text = data.get("message", "Please log in.")
        login_url = data.get("login_url", "")
        site = data.get("site", "")
        buttons = []
        if login_url:
            buttons.append({"text": f"Log in to {site}", "url": login_url})
        buttons.extend([
            {"text": "Ready", "callback": f"graph_resume:{thread_id}:ready"},
            {"text": "Cancel", "callback": f"graph_resume:{thread_id}:cancel"},
        ])
        return SkillResult(response_text=text, buttons=buttons)

    @staticmethod
    def _selection_buttons(
        data: dict, thread_id: str
    ) -> SkillResult:
        text = data.get("response_text", "Select a hotel:")
        # Re-map existing buttons to use graph_resume
        original_buttons = data.get("buttons", [])
        buttons = []
        for b in original_buttons:
            cb = b.get("callback", "")
            if "hotel_select" in cb:
                parts = cb.split(":")
                idx = parts[-1] if parts else "0"
                buttons.append({
                    "text": b["text"],
                    "callback": f"graph_resume:{thread_id}:{idx}",
                })
            elif "hotel_sort" in cb:
                parts = cb.split(":")
                sort_type = parts[-1] if parts else "price"
                buttons.append({
                    "text": b["text"],
                    "callback": f"graph_resume:{thread_id}:sort:{sort_type}",
                })
            elif "hotel_more" in cb:
                buttons.append({
                    "text": b["text"],
                    "callback": f"graph_resume:{thread_id}:more",
                })
            elif "hotel_cancel" in cb:
                buttons.append({
                    "text": b["text"],
                    "callback": f"graph_resume:{thread_id}:cancel",
                })
            else:
                buttons.append(b)
        return SkillResult(response_text=text, buttons=buttons or None)

    @staticmethod
    def _confirm_buttons(
        data: dict, thread_id: str
    ) -> SkillResult:
        text = data.get("confirmation_text", "Confirm booking?")
        buttons = [
            {
                "text": "Confirm",
                "callback": f"graph_resume:{thread_id}:confirm",
            },
            {
                "text": "Back to results",
                "callback": f"graph_resume:{thread_id}:back",
            },
            {
                "text": "Cancel",
                "callback": f"graph_resume:{thread_id}:cancel",
            },
        ]
        return SkillResult(response_text=text, buttons=buttons)

    @staticmethod
    def _is_hotel_request(text: str, intent_data: dict) -> bool:
        """Check if this looks like a hotel booking request."""
        hotel_keywords = {
            "hotel", "отель", "гостиниц", "бронир", "booking",
            "airbnb", "hostel", "хостел", "apartment",
        }
        text_lower = text.lower()
        if any(kw in text_lower for kw in hotel_keywords):
            return True
        if intent_data.get("hotel_city") or intent_data.get("booking_service_type") == "hotel":
            return True
        return False
