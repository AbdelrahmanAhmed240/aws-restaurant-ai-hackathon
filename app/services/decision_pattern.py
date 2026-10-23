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
                        "Customer is asking how much an item costs (e.g., 'What is the price of Basmatio?'), "
                        "inquiring about meal prices (e.g., 'How much is a meal?'), requesting meals within a budget, "
                        "or asking for dish prices."
                    ),
                    "ORDER_CART_OPS": (
                        "Customer explicitly wants to order food, add dishes to cart (e.g., 'I want to order Break Meal'), "
                        "accept/decline combo upgrades, provide checkout details (phone number, delivery address, pickup branch, payment method), "
                        "or confirm an ongoing order draft. Do not choose this for greetings or general questions."
                    ),
                    "ORDER_TRACKING": (
                        "Customer wants to check the status or progress of an existing placed order using an "
                        "order code (e.g. ORD-XXXXX)."
                    ),
                    "KNOWLEDGE_FAQ": (
                        "Customer asks general restaurant questions about branch addresses/locations, opening hours, "
                        "delivery policy/service (e.g., 'Do you offer delivery?'), dietary options (e.g., vegetarian meals), "
                        "cancellation policies, ingredients, contact details, or greets the assistant (e.g., 'hello', 'hi')."
                    ),
                },
            )
            return self._question

    def _fallback_tool_selection(self, message: str, context_state: Optional[Dict[str, Any]] = None) -> ToolDecision:
        """Observable deterministic fallback used only when the 2B neural model is offline or disabled."""
        text = message.lower().strip()
        state = context_state or {}
        has_active_draft = bool(state.get("draft") and state["draft"].get("items"))

        # Pure greetings signal
        greetings = {"hello", "hi", "hey", "good morning", "good evening", "welcome", "greetings", "صباح الخير", "مساء الخير", "مرحبا", "اهلا", "أهلا", "السلام عليكم", "ازيك", "ازيكم"}
        clean_no_punct = text.strip(" ?.!؟")
        if clean_no_punct in greetings or re.match(r"^(?:hello|hi|hey|good\s+morning|good\s+evening|welcome|مرحبا|اهلا|أهلا|السلام عليكم)[!\.\s]*$", text):
            chosen = "KNOWLEDGE_FAQ"

        # Explicit inquiry / FAQ signals take precedence even if draft is active
        faq_signals = (
            "where", "when", "hours", "open", "close", "policy", "branch", "branches", "location", "address",
            "delivery area", "deliver to", "ingredients", "vegetarian", "vegan", "veggie", "نباتي", "نباتية",
            "فرع", "فروع", "مواعيد", "شغالين", "سياسة", "عنوان", "مكان", "بتوصلوا", "في توصيل"
        )
        is_faq_query = any(re.search(rf"\b{re.escape(w)}\b", text) if w.isascii() else w in text for w in faq_signals)
        is_delivery_policy = any(p in text for p in ("do you offer delivery", "do you have delivery", "is delivery available", "delivery fee", "delivery policy", "areas do you deliver", "بتوصلوا", "في توصيل"))
        is_dietary = any(w in text for w in ("vegetarian", "vegan", "veggie", "نباتي", "نباتية"))

        info_inquiry_markers = ("know", "tell me", "which", "what", "show", "list", "display", "see", "how much", "cost", "price", "أعرف", "اعرف", "قولي", "قل لي", "إيه", "ايه", "أي", "اي", "وريني", "اعرض", "بكام", "سعر")
        has_info_inquiry = any(m in text for m in info_inquiry_markers)

        order_action_verbs = (
            "can i order", "want to order", "i'd like to order", "i would like to order",
            "give me", "bring me", "add to order", "add to cart", "deliver to me",
            "أطلب", "اطلب", "هاتلي", "ابعتلي", "ضيف"
        )
        if any(v in text for v in order_action_verbs):
            has_order_action = True
        elif not has_info_inquiry and any(v in text for v in ("i want", "i'd like", "order", "add", "i'll take", "take", "get", "عايز", "عاوز", "أريد", "اريد", "ضيف")):
            has_order_action = True
        else:
            has_order_action = False

        pricing_signals = (
            "under", "budget", "price", "prices", "how much", "cost", "cheapest",
            "سعر", "أسعار", "اسعار", "بكام", "أرخص", "ارخص", "ميزانية",
        )
        has_pricing = any(re.search(rf"\b{re.escape(w)}\b", text) if w.isascii() else w in text for w in pricing_signals) or bool(re.search(r"\b(?:egp|le)\b", text))

        # Order tracking signal
        if re.search(r"\b(?:ord-\d{5,}|track|order\s+status|أوردر|تتبع)\b", text) and re.search(r"ord-\d+", text):
            chosen = "ORDER_TRACKING"
        # Greetings check
        elif clean_no_punct in greetings or re.match(r"^(?:hello|hi|hey|good\s+morning|good\s+evening|welcome|مرحبا|اهلا|أهلا|السلام عليكم)[!\.\s]*$", text):
            chosen = "KNOWLEDGE_FAQ"
        # Delivery policy inquiry
        elif is_delivery_policy and not has_order_action:
            chosen = "KNOWLEDGE_FAQ"
        # Dietary inquiry
        elif is_dietary and not has_order_action:
            chosen = "KNOWLEDGE_FAQ"
        # Full menu browsing signal
        elif re.search(r"\b(?:menu|what do you have|food list|المنيو|قائمة الطعام|بتبيعوا إيه)\b", text) and not re.search(r"\b(?:under|cheapest|cost|price|order|add|isn\'?t\s+on\s+the\s+menu|not\s+on\s+the\s+menu)\b", text):
            chosen = "MENU_QUERY"
        # FAQ inquiry takes precedence if it's an explicit info question without ordering action
        elif (is_faq_query or is_delivery_policy or is_dietary) and not has_order_action:
            chosen = "KNOWLEDGE_FAQ"
        # Pricing and budget queries
        elif has_pricing and not has_order_action:
            chosen = "PRICE_BUDGET_INQUIRY"
        # Active order operations or explicit ordering verbs
        elif has_order_action or (has_active_draft and any(w in text for w in ("pickup", "delivery", "cash", "visa", "confirm", "كاش", "توصيل", "استلام"))):
            chosen = "ORDER_CART_OPS"
        else:
            chosen = "KNOWLEDGE_FAQ"

        probs = {tool: (1.0 if tool == chosen else 0.0) for tool in TOOL_ACTIONS}
        route = "TOOLS" if chosen in ("ORDER_CART_OPS", "ORDER_TRACKING") else "RAG"
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

            route = "TOOLS" if best_tool in ("ORDER_CART_OPS", "ORDER_TRACKING") else "RAG"

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