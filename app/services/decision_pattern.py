"""Reusable #tool-selection Decision Pattern for Strands Decider 2B
Tags: #strands-decider-2b #tool-selection

This module implements a reusable, typed decision dispatcher and intervention handler
pattern using Strands Decider 2B (2B lightweight SLM) paired with Google Gemini response generation.

Architecture:
  Customer Message + Context
              │
              ▼
   ┌───────────────────────────────────────────────┐
   │ ToolSelectionDispatcher (#tool-selection)     │
   │ (Strands Decider 2B ChoiceQuestion Schema)    │
   └───────────────────────────────────────────────┘
              │
     ┌────────┴─────────┬─────────────────┬─────────────────┬─────────────────┐
     ▼                  ▼                 ▼                 ▼                 ▼
 MENU_QUERY    PRICE_BUDGET_INQUIRY ORDER_CART_OPS   ORDER_TRACKING    KNOWLEDGE_FAQ
     │                  │                 │                 │                 │
 (get_full_menu) (query_price_info) (order_session)   (track_order)     (RAG retrieve)
     │                  │                 │                 │                 │
     └──────────────────┴────────┬────────┴─────────────────┴─────────────────┘
                                 │ Grounded Context
                                 ▼
                   ┌───────────────────────────────┐
                   │ Google Gemini Response Gen    │
                   │ Generative Chat Synthesis     │
                   └───────────────────────────────┘
"""
from dataclasses import dataclass, field
import logging
import re
import threading
from typing import Any, Dict, List, Literal, Optional, TypedDict

logger = logging.getLogger(__name__)

# Reusable typed tool targets
ToolActionName = Literal[
    "MENU_QUERY",
    "PRICE_BUDGET_INQUIRY",
    "ORDER_CART_OPS",
    "ORDER_TRACKING",
    "KNOWLEDGE_FAQ",
]

TOOL_ACTIONS: List[ToolActionName] = [
    "MENU_QUERY",
    "PRICE_BUDGET_INQUIRY",
    "ORDER_CART_OPS",
    "ORDER_TRACKING",
    "KNOWLEDGE_FAQ",
]

class ToolDecision(TypedDict):
    """Structured decision output produced by Strands Decider 2B #tool-selection."""
    tool: ToolActionName
    route: str  # "TOOLS" or "RAG"
    confidence: float
    probabilities: Dict[str, float]
    is_fallback: bool
    tags: List[str]

class ToolSelectionDispatcher:
    """Reusable Strands Decider 2B Tool Selection Dispatcher.
    Tags: #strands-decider-2b #tool-selection
    Uses a typed ChoiceQuestion schema over 5 discrete restaurant service tools:
    1. MENU_QUERY: Browsing categories, showing the full food/drinks menu.
    2. PRICE_BUDGET_INQUIRY: Price checks, meals under budget (100 EGP / 50 EGP), cheapest meals.
    3. ORDER_CART_OPS: Adding items to cart, combo upgrades, fulfillment collection, confirmation.
    4. ORDER_TRACKING: Querying status of an existing order code (e.g. ORD-12345).
    5. KNOWLEDGE_FAQ: General restaurant inquiries, branches, operating hours, delivery policies.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._question = None

    def get_choice_question(self):
        """Lazily initialize and cache the typed ChoiceQuestion schema."""
        if self._question is not None:
            return self._question
        with self._lock:
            if self._question is not None:
                return self._question
            from strands_decider.schema import ChoiceQuestion
            self._question = ChoiceQuestion(
                instructions=(
                    "Select the exact restaurant tool action required to handle this customer message "
                    "given the active conversation state. Tags: #tool-selection #strands-decider-2b"
                ),
                criteria={
                    "MENU_QUERY": (
                        "Customer wants to see or explore the full food menu, list available categories, "
                        "meals, sides, sauces, or drinks."
                    ),
                    "PRICE_BUDGET_INQUIRY": (
                        "Customer is asking how much an item costs, inquiring about prices, requesting meals "
                        "within a budget (e.g., under 100 EGP or under 50 EGP), or searching for cheap options."
                    ),
                    "ORDER_CART_OPS": (
                        "Customer wants to order food, add dishes to cart, accept/decline combo upgrades, "
                        "provide fulfillment details (phone number, delivery address, pickup branch, payment method), "
                        "or confirm an ongoing order draft."
                    ),
                    "ORDER_TRACKING": (
                        "Customer wants to check the status or progress of an existing placed order using an "
                        "order code (e.g. ORD-XXXXX)."
                    ),
                    "KNOWLEDGE_FAQ": (
                        "Customer asks general restaurant questions about branch addresses/locations, opening hours, "
                        "delivery areas, cancellation policies, ingredients, or contact details."
                    ),
                },
            )
            return self._question

    def _fallback_tool_selection(self, message: str, context_state: Optional[Dict[str, Any]] = None) -> ToolDecision:
        """Observable deterministic fallback used only when the 2B neural model is offline or disabled."""
        text = message.lower().strip()
        state = context_state or {}
        has_active_draft = bool(state.get("draft") and state["draft"].get("items"))

        # Explicit inquiry / FAQ signals take precedence even if draft is active
        faq_signals = (
            "where", "when", "hours", "open", "close", "policy", "branch", "branches", "location", "address",
            "delivery area", "deliver to", "ingredients", "فرع", "فروع", "مواعيد", "شغالين", "سياسة", "عنوان", "مكان", "بتوصلوا"
        )
        is_faq_query = any(re.search(rf"\b{re.escape(w)}\b", text) if w.isascii() else w in text for w in faq_signals)
        order_action_verbs = ("i want", "i'd like", "order", "add", "أطلب", "عايز", "عاوز", "ضيف", "هاتلي")
        has_order_action = any(v in text for v in order_action_verbs)

        pricing_signals = (
            "under", "budget", "price", "prices", "how much", "cost", "cheapest",
            "سعر", "أسعار", "اسعار", "بكام", "أرخص", "ارخص", "ميزانية",
        )
        has_pricing = any(re.search(rf"\b{re.escape(w)}\b", text) if w.isascii() else w in text for w in pricing_signals) or bool(re.search(r"\b(?:egp|le)\b", text))

        # Order tracking signal
        if re.search(r"\b(?:ord-\d{5,}|track|order\s+status|أوردر|تتبع)\b", text) and re.search(r"ord-\d+", text):
            chosen = "ORDER_TRACKING"
        # Full menu browsing signal
        elif re.search(r"\b(?:menu|what do you have|food list|المنيو|قائمة الطعام|بتبيعوا إيه)\b", text) and not re.search(r"\b(?:under|cheapest|cost|price|order|add)\b", text):
            chosen = "MENU_QUERY"
        # FAQ inquiry takes precedence if it's an explicit info question without ordering action
        elif is_faq_query and not has_order_action:
            chosen = "KNOWLEDGE_FAQ"
        # Pricing and budget queries
        elif has_pricing and not has_order_action:
            chosen = "PRICE_BUDGET_INQUIRY"
        # Active order operations or explicit ordering verbs
        elif has_order_action or any(w in text for w in ("meal", "pickup", "delivery", "cash", "visa", "confirm", "كاش", "توصيل", "استلام")) or has_active_draft:
            chosen = "ORDER_CART_OPS"
        else:
            chosen = "KNOWLEDGE_FAQ"

        probs = {tool: (1.0 if tool == chosen else 0.0) for tool in TOOL_ACTIONS}
        route = "RAG" if chosen == "KNOWLEDGE_FAQ" else "TOOLS"
        return {
            "tool": chosen,
            "route": route,
            "confidence": 1.0,
            "probabilities": probs,
            "is_fallback": True,
            "tags": ["#strands-decider-2b", "#tool-selection"],
        }

    def dispatch(
        self,
        message: str,
        engine: Any = None,
        context_state: Optional[Dict[str, Any]] = None,
        force_fallback: bool = False,
    ) -> ToolDecision:
        """Execute dynamic #tool-selection using Strands Decider 2B.
        Calibrates probabilities and maps intent directly to actionable tool targets.
        """
        if force_fallback or engine is None:
            return self._fallback_tool_selection(message, context_state)

        try:
            import torch
            question = self.get_choice_question()
            context_str = f"User Message: {message}"
            if context_state:
                stage = context_state.get("stage", "idle")
                has_items = bool(context_state.get("draft", {}).get("items"))
                context_str += f"\nActive Draft Stage: {stage}, Cart Has Items: {has_items}"

            # Invoke Strands Decider 2B Choice inference
            with torch.inference_mode():
                if hasattr(engine, "ask"):
                    res = engine.ask(state=context_str, questions={"tool": question})
                    ans = res.answers["tool"]
                    chosen_raw = ans.choice.strip().upper()
                    probabilities = {k: float(v) for k, v in ans.probabilities.items()} if hasattr(ans, "probabilities") and ans.probabilities else {}
                    confidence = float(ans.confidence) if hasattr(ans, "confidence") else 1.0
                else:
                    ans = engine(question, context=context_str)
                    chosen_raw = getattr(ans, "best_choice", getattr(ans, "choice", ""))
                    probabilities = {k: float(v) for k, v in getattr(ans, "probabilities", {}).items()}
                    confidence = float(getattr(ans, "confidence", 1.0))

            best_tool = None
            for tool_candidate in TOOL_ACTIONS:
                if tool_candidate in chosen_raw:
                    best_tool = tool_candidate
                    break

            if not best_tool and probabilities:
                best_tool = max(probabilities.items(), key=lambda kv: kv[1])[0]

            if best_tool not in TOOL_ACTIONS:
                best_tool = "KNOWLEDGE_FAQ"

            route = "RAG" if best_tool == "KNOWLEDGE_FAQ" else "TOOLS"

            logger.info(
                "[STRANDS DECIDER 2B #tool-selection] Tool: %s, Route: %s, Confidence: %.4f",
                best_tool,
                route,
                confidence,
            )

            return {
                "tool": best_tool,
                "route": route,
                "confidence": confidence,
                "probabilities": probabilities,
                "is_fallback": False,
                "tags": ["#strands-decider-2b", "#tool-selection"],
            }
        except Exception as exc:
            logger.warning("[DECIDER TOOL SELECTION EXCEPTION] %s. Engaging observable fallback.", exc)
            return self._fallback_tool_selection(message, context_state)

class InterventionHandler:
    """Reusable Intervention Handler pattern for stateful conversational agents.
    Tags: #strands-decider-2b #tool-selection

    Evaluates whether an incoming customer message requires an out-of-flow intervention
    (e.g., FAQ interruption during order checkout, ambiguous branch clarification, or cancelation)
    and orchestrates tool dispatching with state preservation.
    """
    def __init__(self, dispatcher: Optional[ToolSelectionDispatcher] = None):
        self.dispatcher = dispatcher or ToolSelectionDispatcher()

    def handle_turn(
        self,
        session_id: str,
        message: str,
        engine: Any = None,
        context_state: Optional[Dict[str, Any]] = None,
        force_fallback: bool = False,
    ) -> ToolDecision:
        """Processes customer turn, selecting tool dynamically via Strands Decider 2B."""
        return self.dispatcher.dispatch(
            message=message,
            engine=engine,
            context_state=context_state,
            force_fallback=force_fallback,
        )

# Global singleton instances for direct import and reuse
tool_selection_dispatcher = ToolSelectionDispatcher()
intervention_handler = InterventionHandler(tool_selection_dispatcher)