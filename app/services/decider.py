from typing import Any, TypedDict
import logging
import os
import re
from langgraph.graph import END, StateGraph
from app.services.agent import get_history
from app.services.vector_store import retrieve
from app.services.tools import (
    search_products,
    track_order,
    recommend_products,
    query_price_info,
    _extract_order_code,
)
from app.services.order_session import (
    get_draft,
    clear_draft,
    calculate_draft_totals,
    get_missing_fields,
    format_draft_summary,
    commit_confirmed_order,
    parse_user_entities,
    get_upsell_suggestions,
    AVAILABLE_BRANCHES,
)

logger = logging.getLogger(__name__)

class AgentState(TypedDict, total=False):
    session_id: str
    message: str
    intent: str  # Exactly "RAG" or "TOOLS"
    is_fallback: bool
    route_confidence: float
    route_probabilities: dict[str, float]
    history: list[dict[str, Any]]
    response: str
    context: str
    tool_name: str
    tool_result: dict

import threading

# Global singleton and lock for Strands Decider 2B engine
_decider_engine = None
_decider_lock = threading.Lock()
# Enabled by default; can be disabled only by explicit configuration or testing
_decider_disabled = os.getenv("DECIDER_ENABLED", "True").lower() not in ("true", "1", "yes")

def get_decider_engine():
    """Thread-safe initialization and retrieval of the real Strands Decider 2B engine.
    Ensures the 2B model is loaded exactly once, protects against concurrent initialization,
    and configures sensible thread limits on CPU.
    """
    global _decider_engine, _decider_disabled
    if _decider_disabled:
        return None
    if _decider_engine is not None:
        return _decider_engine

    with _decider_lock:
        if _decider_disabled:
            return None
        if _decider_engine is not None:
            return _decider_engine

        try:
            import torch
            from strands_decider.infer import load_engine

            # Apply CPU thread limit if explicitly configured
            threads_cfg = int(os.getenv("DECIDER_THREADS", "0"))
            if threads_cfg > 0:
                torch.set_num_threads(threads_cfg)
                logger.info("[STRANDS DECIDER 2B] Configured PyTorch CPU threads: %d", threads_cfg)

            checkpoint = os.getenv("STRANDS_DECIDER_MODEL", "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610")

            # If checkpoint is not already a directory path, attempt offline local snapshot resolution
            if not os.path.isdir(checkpoint):
                try:
                    from huggingface_hub import snapshot_download
                    resolved = snapshot_download(checkpoint, local_files_only=True)
                    if os.path.isdir(resolved):
                        checkpoint = resolved
                except Exception:
                    pass

            logger.info("[STRANDS DECIDER 2B] Initializing model engine from: %s", checkpoint)
            with torch.inference_mode():
                _decider_engine = load_engine(checkpoint, device="cpu")
            logger.info("[STRANDS DECIDER 2B] Model engine initialized successfully.")
            return _decider_engine
        except Exception as exc:
            logger.error("[STRANDS DECIDER 2B ERROR] Failed to load model engine: %s. Fallback will be engaged.", exc, exc_info=True)
            return None

def set_decider_disabled(disabled: bool = True):
    """Enable or disable real Decider 2B (used for explicit test isolation or mode toggling)."""
    global _decider_disabled
    _decider_disabled = disabled

def _format_meal_includes(desc: str) -> str:
    """Format meal ingredients as a clean comma-separated list."""
    if not desc:
        return ""

    translations = {
        "ورك فرخة بروستد": "Broasted chicken thigh",
        "نصف فرخة بروستد": "Half broasted chicken",
        "ثلاث قطع ستربس": "Three strips pieces",
        "خمس قطع ستربس": "Five strips pieces",
        "بطاطس": "Fries",
        "خبز": "Bread",
        "ثومية صغيرة": "Garlic dip",
        "ثومية": "Garlic dip",
        "كاتشب": "Ketchup",
        "كول سلو": "Coleslaw",
        "رز بسمتي": "Basmati rice",
        "أرز بسمتي": "Basmati rice",
        "ستربس": "Strips",
    }

    items = []
    for line in desc.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue
        # Only take bullet lines or strip bullet markers
        if line_clean.startswith(("-", "*", "•")):
            item = line_clean.lstrip("-*• ").strip()
        else:
            item = line_clean.strip()

        if item and not any(word in item.lower() for word in ["تحتوي على", "يحتوي على", "وجبة", "contains:"]):
            cleaned = translations.get(item.strip(" :-"), item.strip(" :-"))
            if cleaned:
                items.append(cleaned)

    return ", ".join(items) if items else desc.replace("\n", " ").strip()

def _format_menu_grouped(items: list[dict]) -> str:
    """Format menu items grouped by category."""
    order = ["Meals", "Add-ons", "Sauces", "Drinks", "Extras"]
    emojis = {
        "Meals": "🍗", "Add-ons": "➕", "Sauces": "🥫",
        "Drinks": "🥤", "Extras": "🍟",
    }

    grouped = {}
    for item in items:
        category = item.get("category") or "Extras"
        grouped.setdefault(category, []).append(item)

    sections = ["### 📋 Our Menu"]
    categories = [c for c in order if c in grouped]
    categories += [c for c in grouped if c not in order]

    for category in categories:
        sections.append(f"\n#### {emojis.get(category, '📦')} {category}")
        for item in grouped[category]:
            name = item.get("name", "")
            price = item.get("price") or 0
            sections.append(f"* **{name} — {price:.0f} EGP**" if category == "Meals"
                            else f"* **{name}** — {price:.0f} EGP")

            if category == "Meals":
                includes = _format_meal_includes(item.get("description") or "")
                combo = item.get("combo_price") or 0
                if includes:
                    sections.append(f"  * Includes: {includes}.")
                if combo > 0:
                    sections.append(f"  * Combo upgrade: +{combo:.0f} EGP for fries and a drink.")

    return "\n".join(sections)

def _format_branch_directory() -> str:
    """Format authoritative list of restaurant pickup branches grouped by city."""
    return (
        "### 🏬 Our Available Branches for Pickup:\n\n"
        "#### 📍 Cairo Branches:\n"
        "* **Mohandessin Branch**: 45 El Batal Ahmed Abdel Aziz Street, off Gameat El Dowal El Arabiya Street.\n"
        "* **Mokattam Branch**: Street 9, extension of Fountain Square, next to Etisalat store, in front of Monginis.\n"
        "* **Sheraton Branch**: 43 Sheraton Housing, First Zone, Ankara Street.\n\n"
        "#### 📍 Alexandria Branches:\n"
        "* **Glim Branch**: 30 El-Ezaa Street (Radio Street), Glim.\n"
        "* **Mandara Branch**: El Geish Road, extension of Abdel Halim Mahmoud Mosque Street, in front of Santos Cafe.\n"
        "* **Camp Caesar Branch**: Camp Caesar, Corniche beachfront, next to Wali Cafeteria.\n"
        "* **Smouha Branch 1**: Smouha Cooperatives, Hatem Mosque Street, behind Security Directorate.\n"
        "* **Smouha Branch 2**: Commercial Market, Hatem Mosque Street.\n"
        "* **Bahary Branch**: 19 26th of July Road, next to El-Saidi Gelato.\n"
        "* **Sidi Bishr Branch**: El-Eisawy Street, in front of Electricity Company.\n"
        "* **Mahrousa Branch**: El Geish Road, right beside El-Mahrousa Tunnel and El-Mahrousa Hotel.\n\n"
        "Customers can select any of these branches for pickup orders!"
    )

def _format_product_item_lines(items: list[Any]) -> list[str]:
    """Format structured product details consistently across recommendations, meal listings, and queries."""
    lines = []
    for item in items:
        name = getattr(item, "name", None) or (item.get("name") if isinstance(item, dict) else "")
        price = getattr(item, "price", 0.0) if hasattr(item, "price") else (item.get("price", 0.0) if isinstance(item, dict) else 0.0)
        combo = getattr(item, "combo_price", 0.0) if hasattr(item, "combo_price") else (item.get("combo_price", 0.0) if isinstance(item, dict) else 0.0)
        cat = getattr(item, "category", "") if hasattr(item, "category") else (item.get("category", "") if isinstance(item, dict) else "")
        desc = getattr(item, "description", "") if hasattr(item, "description") else (item.get("description", "") if isinstance(item, dict) else "")
        if cat == "Meals":
            includes = _format_meal_includes(desc or "")
            lines.append(f"**{name} — {price:.0f} EGP**")
            if includes:
                lines.append(f"* Includes: {includes}.")
            if combo and combo > 0:
                lines.append(f"* Combo upgrade: +{combo:.0f} EGP for fries and a drink.")
            lines.append("")
        else:
            lines.append(f"* **{name}** ({cat}) — {price:.0f} EGP")
    return lines

def _fallback_route_intent(message: str, session_id: str = "") -> str:
    """
    Observable Deterministic Fallback Router:
    Used only when Strands Decider 2B engine is offline, disabled, or encounters runtime errors.
    Returns exactly "RAG" or "TOOLS".
    """
    text = (message or "").strip().lower()

    # 1. Order tracking
    tracking_signals = ("track", "status", "حالة", "تتبع", "where is my order", "where's my order", "فين طلبي", "وصل لفين")
    has_order_code = bool(_extract_order_code(message))
    if any(sig in text for sig in tracking_signals) or (has_order_code and ("order" in text or "طلب" in text)):
        return "TOOLS"

    # 2. Confirmation signals
    confirm_signals = [
        "confirm", "place order", "submit order", "yes please",
        "تأكيد", "أكد", "تأكيد الطلب", "اكد الطلب", "اعتمد", "سجل الطلب", "نفذ الطلب"
    ]
    if any(sig in text for sig in confirm_signals):
        return "TOOLS"

    # Inspect active draft
    draft = get_draft(session_id) if session_id else {}
    has_active_draft = bool((draft.get("items") or draft.get("order_type")) and draft.get("stage") != "confirmed")

    # 3. Upsell declines or accepts
    decline_signals = ["no", "no thanks", "no thank you", "none", "لا", "لا شكرا", "لا شكراً", "لا تمام", "تمام كده", "مش عايز", "مش عاوز", "كفاية", "بس كده"]
    combo_signals = ["make it combo", "make them combo", "add combo", "combo please", "upgrade to combo", "خليهم كومبو", "مع كومبو", "ضيف كومبو", "نعم كومبو", "عايز كومبو", "عاوز كومبو"]
    if has_active_draft:
        clean_text = text.strip(" .!?,")
        if (clean_text in decline_signals or any(clean_text.startswith(s + " ") for s in ["no", "no thanks", "لا", "لا شكرا"])) or any(sig in text for sig in combo_signals):
            return "TOOLS"

    # 4. Cancellation attempt vs Policy inquiry
    if any(sig in text for sig in ("cancel", "إلغاء", "الغاء", "الغي", "كنسل")):
        is_policy_inquiry = any(w in text for w in ("policy", "rules", "can i", "could i", "how", "what", "fee", "fees", "سياسة", "شروط", "هل", "ممكن", "ينفع", "رسوم", "لو حبيت")) or "?" in text or "؟" in text
        if is_policy_inquiry:
            return "RAG"
        return "TOOLS"

    # 2. Informational questions take precedence unless an explicit ordering action is stated
    # Check for question markers or inquiry patterns
    inquiry_question_starters = [
        "what", "how", "where", "when", "why", "who", "which", "can i", "could i", "do you", "is there", "are there", "tell me",
        "show me", "list", "أين", "فين", "ما هي", "ايه هي", "إيه هي", "كام", "هل", "ممكن اعرف"
    ]
    is_question_structure = "?" in text or "؟" in text or any(re.search(rf"\b{re.escape(k)}\b", text) for k in inquiry_question_starters)
    
    info_topic_signals = [
        "hours", "open", "close", "working hours", "branch", "branches", "location", "locations", "address",
        "ingredients", "contain", "include", "policy", "fee", "fees", "deliver to", "delivery to", "area", "areas",
        "مواعيد", "شغالين", "بيفتح", "بيقفل", "ساعات العمل", "فروع", "فرعكم", "عنوان", "مكان",
        "مكونات", "يحتوي", "فيه", "رسوم", "سياسة", "مصاريف", "مناطق", "بتوصلوا"
    ]
    # An inquiry query must either have an explicit question structure + topic, or contain an explicit query phrase
    is_explicit_info_query = (
        is_question_structure and (any(sig in text for sig in info_topic_signals) or "?" in text or "؟" in text)
    ) or any(re.search(rf"\b(?:what\s+are|where\s+are|show|list)\s+.*(?:branches|locations|menu|hours)\b", text) for _ in [1])

    # Explicit ordering verbs (actual intent to buy or add items to an order)
    order_action_verbs = [
        "place an order", "create order", "i want to order", "order now", "عاوز أطلب", "عايز أطلب", "أطلب", "اطلب", "طلب أوردر",
        "i want", "i'd like", "give me", "bring me", "add", "عاوز", "عايز", "أريد", "اريد", "هاتلي", "ابعتلي", "وصلني", "ضيف",
        "recommend", "suggest", "ترشيح", "رشحلي", "اقتراح"
    ]
    has_order_action = any(v in text for v in order_action_verbs)

    # Fulfillment detail mentions (specifying address, delivery, pickup)
    fulfillment_words = [
        "pickup", "dine in", "dine-in", "استلام", "صالة", "طاولة", "ترابيزة",
        "cash", "visa", "كاش", "فيزا",
        "street", "st.", "apartment", "apt", "floor", "building", "address", "delivery", "شارع", "شقة", "دور", "عمارة", "عنوان", "توصيل"
    ]
    has_fulfillment_detail = any(w in text for w in fulfillment_words)

    # Menu item mentions
    menu_item_signals = (
        "quarter broasted", "broasted", "chicken strips", "strips", "break meal", "break",
        "fatta", "basmatio", "french fries", "fries", "basmati rice", "rice", "coleslaw",
        "garlic dip", "kaiser bun", "bun", "bbq", "cheddar", "ranch", "sweet chili", "soft drink", "water",
        "بسمتيو", "بروستد", "ستربس", "بريك", "فتة", "بطاطس", "أرز", "رز", "ثومية", "كول سلو", "شيدر"
    )
    has_menu_item = any(item in text for item in menu_item_signals)
    has_phone = bool(re.search(r"(?:(?:\+?20)|0)?1[0125]\d{8}\b", text))

    # If it's an explicit info inquiry without explicit ordering verbs/phone, route to RAG
    if is_explicit_info_query and not has_order_action and not has_phone:
        return "RAG"

    if has_order_action or has_phone or has_fulfillment_detail or has_menu_item:
        return "TOOLS"

    if has_active_draft:
        if is_explicit_info_query:
            return "RAG"
        return "TOOLS"

    return "RAG"

_ROUTING_QUESTION = None
_ROUTING_QUESTION_LOCK = threading.Lock()

def _get_routing_question():
    """Returns cached, pre-rendered ChoiceQuestion to avoid recreating schema objects per request."""
    global _ROUTING_QUESTION
    if _ROUTING_QUESTION is not None:
        return _ROUTING_QUESTION
    with _ROUTING_QUESTION_LOCK:
        if _ROUTING_QUESTION is not None:
            return _ROUTING_QUESTION
        from strands_decider.schema import ChoiceQuestion
        _ROUTING_QUESTION = ChoiceQuestion(
            instructions="Classify whether this restaurant customer message requires general information/policies (RAG) or ordering/fulfillment/transactional tools (TOOLS).",
            criteria={
                "RAG": "Inquiries about restaurant details, branch locations, operating hours, delivery fees, cancellation policy, ingredients, general FAQs.",
                "TOOLS": "Placing food orders, adding items to cart, menu pricing, recommendations, meal searches, providing fulfillment details (phone, delivery address, branch, payment method), order confirmation, order status tracking."
            }
        )
        return _ROUTING_QUESTION

def decide_route(message: str, session_id: str = "", force_fallback: bool = False) -> dict:
    """
    Strands Decider 2B High-Level Decision Point:
    Classifies customer message into exactly one of two choices:
    - RAG: General restaurant knowledge, policies, opening hours, branch locations, FAQ.
    - TOOLS: Menu browsing, product pricing, recommendations, order drafting, details collection, order confirmation, tracking.

    Returns:
        dict:
            - route: "RAG" or "TOOLS"
            - is_fallback: bool
            - confidence: float
            - probabilities: dict[str, float]
    """
    draft = get_draft(session_id) if session_id else {}
    has_active_draft = bool((draft.get("items") or draft.get("order_type")) and draft.get("stage") != "confirmed")

    if not force_fallback:
        engine = get_decider_engine()
        if engine is not None:
            try:
                import torch
                question = _get_routing_question()
                # Provide conversational context to the Decider state when customer is in active ordering/fulfillment flow
                if has_active_draft:
                    decider_state = f"Active draft: customer has items in cart and is in the process of ordering or providing fulfillment details.\nCustomer message: {message}"
                else:
                    decider_state = message

                with torch.inference_mode():
                    res = engine.ask(state=decider_state, questions={"route": question})
                ans = res.answers["route"]
                chosen = ans.choice.strip().upper()
                route = "RAG" if "RAG" in chosen else "TOOLS"
                logger.info("[STRANDS DECIDER 2B] Decision: %s (confidence: %.4f, probs: %s)", route, ans.confidence, ans.probabilities)
                return {
                    "route": route,
                    "is_fallback": False,
                    "confidence": float(ans.confidence),
                    "probabilities": {k: float(v) for k, v in ans.probabilities.items()},
                }
            except Exception as exc:
                logger.error("[STRANDS DECIDER 2B ERROR] Model inference execution failed: %s. Using observable fallback.", exc, exc_info=True)

    # Observable Fallback
    logger.warning("[DECIDER FALLBACK] Executing observable deterministic fallback routing.")
    fallback_route = _fallback_route_intent(message, session_id=session_id)
    return {
        "route": fallback_route,
        "is_fallback": True,
        "confidence": 1.0,
        "probabilities": {fallback_route: 1.0, ("TOOLS" if fallback_route == "RAG" else "RAG"): 0.0},
    }

def router_node(state: AgentState) -> AgentState:
    """Classifies message into 'RAG' or 'TOOLS' using Strands Decider 2B."""
    session_id = state.get("session_id", "default")
    message = state.get("message", "")
    dec_result = decide_route(message, session_id=session_id)
    state["intent"] = dec_result["route"]
    state["is_fallback"] = dec_result.get("is_fallback", False)
    state["route_confidence"] = dec_result.get("confidence", 1.0)
    state["route_probabilities"] = dec_result.get("probabilities", {})
    return state

def rag_node(state: AgentState) -> AgentState:
    """
    Unified Information Path (Path A):
    Handles all general knowledge, hours, branch, and policy questions.
    Also handles product browsing or recommendations if explicitly directed here.
    """
    from app.models.product import Product

    message = state.get("message", "")
    session_id = state.get("session_id", "default")
    text_lower = (message or "").lower()
    pieces = []

    # Safety: If customer has an active draft and provides fulfillment info, parse and preserve it
    draft = get_draft(session_id)
    if draft.get("items") or draft.get("order_type"):
        parse_user_entities(session_id, message)

    # 1. Deterministic price comparison questions
    price_info = query_price_info(message)
    if price_info.get("ok"):
        pieces.append(price_info.get("text", ""))
        state["context"] = "\n\n".join(pieces)
        state["tool_name"] = "query_price_info"
        state["tool_result"] = price_info
        return state

    # 2. Recommendation inquiries
    rec_signals = ["recommend", "suggest", "best", "hungry", "what should i get", "spicy", "ترشيح", "رشحلي", "اقتراح"]
    if any(sig in text_lower for sig in rec_signals):
        rec_result = recommend_products(message, limit=3)
        if rec_result.get("ok") and rec_result.get("items"):
            lines = ["### 🌟 Recommended Options\n"] + _format_product_item_lines(rec_result["items"])
            pieces.append("\n".join(lines).strip())
            state["context"] = "\n\n".join(pieces)
            state["tool_name"] = "recommend_products"
            state["tool_result"] = rec_result
            return state

    # 3. All Meals query
    if any(kw in text_lower for kw in ("all meals", "available meals", "what meals", "list meals", "show meals", "الوجبات", "كل الوجبات")):
        meals = Product.query.filter(Product.category == "Meals", Product.is_available == True).order_by(Product.price.asc()).all()
        lines = ["### 🍗 Available Meals\n"] + _format_product_item_lines(meals)
        pieces.append("\n".join(lines).strip())
        state["context"] = "\n\n".join(pieces)
        state["tool_name"] = "list_meals"
        state["tool_result"] = {"ok": True, "count": len(meals)}
        return state

    # 4. Full menu query
    is_menu_query = bool(re.search(
        r"\b(?:menu|can\s+i\s+see\s+(?:the\s+)?menu|show\s+(?:me\s+)?(?:the\s+)?menu|what\s+do\s+you\s+have|display\s+(?:the\s+)?(?:full\s+)?menu|full\s+menu|view\s+(?:the\s+)?menu|what\'?s\s+on\s+the\s+menu)\b",
        text_lower
    )) or any(kw in text_lower for kw in ("منيو", "قائمة الطعام", "قائمه الطعام", "قائمة", "قائمه", "وريني المنيو", "عايز اشوف المنيو", "عاوز اشوف المنيو"))

    if is_menu_query:
        product_results = search_products("", limit=50)
        items = product_results.get("items") or []
        if not product_results.get("ok") or not items:
            err_msg = "⚠️ Our menu is currently unavailable. Please check back shortly."
            state["response"] = err_msg
            state["context"] = err_msg
            state["tool_name"] = "menu_listing"
            state["tool_result"] = {"ok": False, "count": 0, "error": "No products available"}
            return state

        menu_text = _format_menu_grouped(items)
        state["response"] = menu_text
        state["context"] = menu_text
        state["tool_name"] = "menu_listing"
        state["tool_result"] = {"ok": True, "count": len(items)}
        return state

    # 5. Branch directory & pickup location inquiries
    branch_inquiry_patterns = [
        r"\b(?:what\s+(?:are\s+)?(?:the\s+)?branches|where\s+are\s+(?:the\s+|your\s+)?branches|list\s+(?:the\s+)?branches|show\s+(?:the\s+)?branches|which\s+branches|branches\s+(?:can\s+i|available|offer)|where\s+can\s+i\s+(?:pick\s*up|collect)|pick\s*up\s+from|locations|what\s+are\s+your\s+locations)\b",
        r"(?:فروع|فرعكم|مكانكم|اماكنكم|أماكنكم|عناوينكم|منين\s*استلم|استلم\s*منين|الفروع\s*المتاحة)",
    ]
    if any(re.search(pat, text_lower) for pat in branch_inquiry_patterns) or ("branch" in text_lower and any(q in text_lower for q in ("what", "where", "which", "how", "list", "show", "can i", "?"))):
        branch_dir = _format_branch_directory()
        pieces.append(branch_dir)
        state["context"] = "\n\n".join(pieces)
        state["tool_name"] = "branch_directory"
        state["tool_result"] = {"ok": True, "count": len(AVAILABLE_BRANCHES)}
        return state

    # 6. Semantic RAG retrieval from ChromaDB knowledge base
    hits = retrieve(message, top_k=4)
    relevant_hits = [h for h in hits if h.get("score") is None or h.get("score") <= 0.80]
    for hit in relevant_hits:
        content = hit.get("content") or ""
        if content.strip():
            pieces.append(content.strip())

    # Detect questions about ordering availability
    order_inquiry_patterns = [
        r"\b(?:can\s*i\s*order|how\s*(?:can\s*i|do\s*i|to)\s*order|order\s*(?:from\s*here|online|here)|is\s*ordering\s*available)\b",
        r"(?:ممكن\s*اطلب|اقدر\s*اطلب|ينفع\s*اطلب|عايز\s*اطلب\s*من\s*هنا|عاوز\s*اطلب\s*من\s*هنا|الطلب\s*متاح)",
    ]
    if any(re.search(pat, text_lower) for pat in order_inquiry_patterns):
        ordering_info = (
            "### 🍽️ Ordering Availability:\n"
            "* Yes, ordering is available! Customers can place food orders directly through this chat.\n"
            "* Service options: Delivery (all Cairo areas, 30-45 minutes, 25 EGP delivery fee, Cash on delivery), Pickup (from our branches), or Dine-in.\n"
            "* Customers can view our menu or tell us the items they would like to order."
        )
        pieces.append(ordering_info)

    # Augment with live structured product details if query mentions menu items
    product_results = search_products(message, limit=3)
    if product_results.get("ok") and product_results.get("items"):
        p_lines = _format_product_item_lines(product_results["items"])
        if p_lines:
            pieces.append("\n".join(p_lines).strip())

    if not pieces:
        pieces.append("I don't have specific information for that request.")

    state["context"] = "\n\n".join(pieces)
    state["tool_name"] = "rag_knowledge"
    state["tool_result"] = {"hits_count": len(relevant_hits)}
    return state

def _is_confirmation_intent(text: str, draft: dict[str, Any]) -> bool:
    """Check if message represents an unambiguous order confirmation intent."""
    t = (text or "").strip().lower()
    if not t:
        return False

    if "?" in t or "؟" in t:
        return False

    negation_patterns = [
        r"\b(?:don'?t|do not|not|never|no|stop|wait|hold|delay)\b",
        r"(?:مش|لا|بلاش|متأكدش|متاكدش|ما تأكدش|ما تاكدش|استنى|استني|لحظة|ثانية|مهلا|توقف)\b",
    ]
    if any(re.search(pat, t) for pat in negation_patterns):
        return False

    modification_patterns = [
        r"\b(?:but|however|change|modify|update|remove|delete|cancel|replace|instead|except)\b",
        r"(?:بس|لكن|غير|عدل|احذف|شيل|امسح|بدل|ما عدا|إلا|الا)\b",
    ]
    if any(re.search(pat, t) for pat in modification_patterns):
        return False

    explicit_confirm_patterns = [
        r"\b(?:confirm(?:ed|ing)?(?:\s+(?:the|my|last)?\s*order)?|place\s+(?:the|my)?\s*order|submit\s+(?:the|my)?\s*order|complete\s+(?:the|my)?\s*order|finish\s+(?:the|my)?\s*order)\b",
        r"(?:تأكيد|أكد|اكد|اعتمد|سجل|نفذ)(?:\s+(?:الطلب|الأوردر|الاوردر|أخر طلب|اخر طلب))?",
    ]
    if any(re.search(pat, t) for pat in explicit_confirm_patterns):
        return True

    is_awaiting = draft.get("stage") == "awaiting_confirmation"
    has_items = bool(draft.get("items"))
    missing = get_missing_fields(draft) if has_items else ["items"]

    if is_awaiting or (has_items and not missing):
        affirmative_tokens = {
            "yes", "yeah", "yep", "sure", "ok", "okay", "proceed",
            "تمام", "أيوة", "ايوة", "نعم", "موافق", "ماشي", "اه", "أه", "أكيد", "اكيد",
        }
        words = set(re.findall(r"[\w]+", t))
        if any(w in affirmative_tokens for w in words) and len(words) <= 4:
            return True

    return False

def _format_confirmed_order_response(result: dict[str, Any], draft: dict[str, Any]) -> str:
    """Format the authoritative confirmed order message strictly using persisted database data."""
    order_code = result.get("order_code") or draft.get("confirmed_order_code", "UNKNOWN")
    calc = calculate_draft_totals(draft)
    order_type = result.get("order_type") or draft.get("order_type", "")
    type_display = {
        "delivery": "🚀 Delivery",
        "pickup": "🏬 Pickup",
        "dine_in": "🍽️ Dine-in",
    }.get(order_type, order_type)

    customer_name = result.get("customer_name") or draft.get("customer_name", "")
    customer_phone = result.get("customer_phone") or draft.get("customer_phone", "")
    payment_method = result.get("payment_method") or draft.get("payment_method", "")
    status = result.get("status", "In Kitchen")

    lines = [
        "🎉 **Your order has been placed successfully!**\n",
        f"📋 **Order Code**: `{order_code}`",
        f"👤 **Customer**: {customer_name}",
        f"📞 **Phone**: {customer_phone}",
        f"📦 **Order Type**: {type_display}",
    ]

    addr = result.get("delivery_address") or draft.get("delivery_address")
    branch = result.get("pickup_branch") or draft.get("pickup_branch")
    table = result.get("table_number") or draft.get("table_number")
    if addr:
        lines.append(f"📍 **Delivery Address**: {addr}")
    elif branch:
        lines.append(f"🏬 **Pickup Branch**: {branch}")
    elif table:
        lines.append(f"🍽️ **Table Number**: {table}")

    lines.append(f"💳 **Payment Method**: {payment_method}")
    lines.append(f"Status: **{status}**\n")

    lines.append("#### 🛒 Order Items:")
    items = result.get("items")
    if items:
        for it in items:
            p_name = it.get("product_name", "")
            qty = it.get("quantity", 1)
            unit_p = it.get("unit_price", 0.0)
            combo_str = " *(Combo)*" if it.get("is_combo") else ""
            notes_str = f" [{it['notes']}]" if it.get("notes") else ""
            lines.append(f"* **{p_name}**{combo_str} x{qty}{notes_str} — {unit_p * qty:.0f} EGP")
    else:
        for it in calc.get("items", []):
            combo_str = " *(Combo)*" if it.get("is_combo") else ""
            notes_str = f" [{it['notes']}]" if it.get("notes") else ""
            lines.append(f"* **{it['name']}**{combo_str} x{it['quantity']}{notes_str} — {it['line_total']:.0f} EGP")

    total = result.get("total_price", calc.get("total_price", 0.0))
    lines.append(f"\n**Total Amount**: {total:.0f} EGP\n")
    lines.append(f"Thank you for choosing our restaurant! You can track your order status anytime using order code `{order_code}`.")
    return "\n".join(lines)

def order_tool_node(state: AgentState) -> AgentState:
    """
    Order Operations Path (Path B):
    - Manages draft lifecycle: parses entities, adds items, calculates totals.
    - Conducts Guided Upselling before collecting customer fulfillment details.
    - Asks for missing required fields sequentially.
    - Validates and executes transactional order confirmation and tracking.
    - Handles mixed messages by retrieving RAG context if informational questions are present.
    """
    session_id = state.get("session_id", "default")
    message = state.get("message", "")
    text_lower = (message or "").strip().lower()

    # Intercept explicit full-menu requests if routed to TOOLS (e.g. from general 'what do you have')
    # but only if user isn't trying to place an explicit order or modify items
    is_menu_query = bool(re.search(
        r"\b(?:menu|can\s+i\s+see\s+(?:the\s+)?menu|show\s+(?:me\s+)?(?:the\s+)?menu|what\s+do\s+you\s+have|display\s+(?:the\s+)?(?:full\s+)?menu|full\s+menu|view\s+(?:the\s+)?menu|what\'?s\s+on\s+the\s+menu)\b",
        text_lower
    )) or any(kw in text_lower for kw in ("منيو", "قائمة الطعام", "قائمه الطعام", "قائمة", "قائمه", "وريني المنيو", "عايز اشوف المنيو", "عاوز اشوف المنيو"))
    is_explicit_order_action = any(v in text_lower for v in ("i want", "i'd like", "give me", "bring me", "add", "عاوز", "عايز", "أريد", "اريد", "هاتلي", "ابعتلي", "وصل", "وصلني", "ضيف"))

    if is_menu_query and not is_explicit_order_action:
        product_results = search_products("", limit=50)
        items = product_results.get("items") or []
        if not product_results.get("ok") or not items:
            err_msg = "⚠️ Our menu is currently unavailable. Please check back shortly."
            state["response"] = err_msg
            state["context"] = err_msg
            state["tool_name"] = "menu_listing"
            state["tool_result"] = {"ok": False, "count": 0, "error": "No products available"}
            return state

        menu_text = _format_menu_grouped(items)
        state["response"] = menu_text
        state["context"] = menu_text
        state["tool_name"] = "menu_listing"
        state["tool_result"] = {"ok": True, "count": len(items)}
        return state

    # 1. Parse entities into draft
    parse_user_entities(session_id, message)
    draft = get_draft(session_id)

    result: dict = {"ok": True}
    context_lines = []

    # Mixed message support: Check if customer also asked an informational question
    info_triggers = [
        "have", "contain", "ingredients", "what is", "how much", "price", "fee", "cost",
        "branch", "branches", "hours", "open", "close", "deliver to", "delivery to",
        "do you deliver", "can you deliver", "policy", "policies", "location", "address",
        "سعر", "مكونات", "فيه", "بكام", "فرع", "فروع", "مواعيد", "رسوم", "توصيل ل", "بتوصلوا"
    ]
    is_question = (
        "?" in text_lower or "؟" in text_lower
        or any(re.search(rf"\b{re.escape(k)}\b", text_lower) for k in [
            "what", "how", "where", "when", "why", "who", "which", "can i", "do you", "is there", "are there"
        ])
    )
    has_mixed_info = is_question or any(k in text_lower for k in info_triggers)
    hits = []
    if has_mixed_info:
        # If inquiry is specifically about branches, provide authoritative branch directory
        if any(b_kw in text_lower for b_kw in ("branch", "branches", "where can i pick up", "pickup branch", "فروع", "فرع")):
            context_lines.append(_format_branch_directory())
            context_lines.append("IMPORTANT: Answer the customer's branch question by listing our branches and their addresses clearly, while continuing to assist them with their order.")
        else:
            hits = retrieve(message, top_k=3)
            if hits:
                context_lines.append("### ℹ️ Knowledge Base Context:\n" + "\n".join(h["content"] for h in hits))
                context_lines.append("IMPORTANT FOR MIXED INQUIRY: The customer asked a question alongside their order. You MUST directly answer their question using the Knowledge Base Context above, while also addressing their order.")

    # 2. Check for Order Tracking
    is_cancel_intent = any(k in text_lower for k in ("cancel", "إلغاء"))
    tracking_words = ["track", "status", "where is my order", "where's my order", "where is order", "where's order", "حالة", "تتبع", "وصل لفين", "جاهز", "فين طلبي"]
    explicit_code = _extract_order_code(message)
    target_code = explicit_code or draft.get("confirmed_order_code")
    is_tracking_inquiry = not is_cancel_intent and (any(k in text_lower for k in tracking_words) or bool(explicit_code))

    if is_tracking_inquiry:
        if target_code:
            track_res = track_order(order_code=target_code)
            if track_res.get("ok"):
                cur_status = track_res.get("status", "Unknown")
                c_name = track_res.get("customer_name") or "Valued Customer"
                total_val = track_res.get("total_price", 0.0)
                status_expl = {
                    "In Kitchen": "Being prepared in our kitchen right now 👨‍🍳🔥",
                    "Ready": "Ready for pickup or handover! 📦✨",
                    "Delivered": "Delivered successfully! Enjoy your meal! 🎉🚀",
                    "Cancelled": "Cancelled. ❌",
                }.get(cur_status, cur_status)

                resp_text = (
                    f"### 📍 Order Status: `{target_code}`\n\n"
                    f"* **Current Status**: **{cur_status}** ({status_expl})\n"
                    f"* **Customer**: {c_name}\n"
                    f"* **Order Total**: {total_val:.0f} EGP\n\n"
                    f"Our database reflects the latest real-time status of your order."
                )
                state["tool_name"] = "track_order"
                state["tool_result"] = track_res
                state["response"] = resp_text
                state["context"] = resp_text
                return state
            else:
                err_msg = track_res.get("error", "Order not found.")
                resp_text = f"❌ {err_msg} Please double-check your order code."
                state["tool_name"] = "track_order"
                state["tool_result"] = track_res
                state["response"] = resp_text
                state["context"] = resp_text
                return state
        else:
            resp_text = "Please provide your **Order Code** (e.g., `ORD-12345`) so I can retrieve the real-time status of your order from our database."
            state["tool_name"] = "track_order"
            state["tool_result"] = {"ok": False, "missing": "order_code"}
            state["response"] = resp_text
            state["context"] = resp_text
            return state

    # 3. Check for Cancellation
    is_cancel_mention = any(k in text_lower for k in ("cancel", "إلغاء", "الغاء", "الغي", "كنسل"))
    if is_cancel_mention:
        order_code = _extract_order_code(message)
        is_policy_inquiry = (
            any(w in text_lower for w in ("policy", "rules", "can i", "could i", "how", "what", "fee", "fees", "سياسة", "شروط", "هل", "ممكن", "ينفع", "رسوم", "لو حبيت"))
            or "?" in text_lower
            or "؟" in text_lower
        )
        if is_policy_inquiry:
            resp_text = (
                "ℹ️ **Cancellation Policy**:\n"
                "- Once an order has been confirmed and placed, it cannot be cancelled as preparation begins immediately in the kitchen.\n"
                "- You can freely modify or cancel an unconfirmed draft at any time before placing your order."
            )
            state["tool_name"] = "cancellation_policy"
            state["tool_result"] = {"ok": True, "action": "policy_info"}
            state["response"] = resp_text
            state["context"] = resp_text
            return state
        elif order_code or draft.get("confirmed_order_code"):
            resp_text = (
                "❌ **Order Cancellation is Not Supported**: "
                "Once an order has been confirmed and placed, it cannot be cancelled as preparation begins immediately in the kitchen. "
                "You can track your order status using your Order Code."
            )
            state["tool_name"] = "cancellation_notice"
            state["tool_result"] = {"ok": False, "error": "Order cancellation is not supported."}
            state["response"] = resp_text
            state["context"] = resp_text
            return state
        else:
            clear_draft(session_id)
            resp_text = "Your unconfirmed draft order has been cleared."
            state["tool_name"] = "clear_draft"
            state["tool_result"] = {"ok": True, "action": "draft_cleared"}
            state["response"] = resp_text
            state["context"] = resp_text
            return state

    # 4. Check for Confirmation
    if _is_confirmation_intent(message, draft):
        if not draft.get("items"):
            try:
                from app.models.chat import ChatMessage
                prior_msgs = ChatMessage.query.filter_by(session_id=session_id, role="user").order_by(ChatMessage.created_at.asc()).all()
                for pm in prior_msgs:
                    parse_user_entities(session_id, pm.content)
                draft = get_draft(session_id)
            except Exception:
                pass

        if not draft.get("items"):
            result = {"ok": False, "error": "Cannot confirm empty order."}
            state["tool_name"] = "confirm_order"
            state["tool_result"] = result
            state["response"] = "⚠️ Cannot confirm an empty order. Please select your desired meal first."
            state["context"] = state["response"]
            return state

        if draft.get("stage") == "offering_extras" and not draft.get("upsell_declined"):
            result = {"ok": False, "error": "Order still in upselling stage."}
            state["tool_name"] = "confirm_order"
            state["tool_result"] = result
            state["response"] = "Please first choose if you'd like to add combo upgrades, drinks, or sauces, then we will collect your details and confirm."
            state["context"] = state["response"]
            return state

        missing = get_missing_fields(draft)
        if missing:
            result = {
                "ok": False,
                "error": f"Cannot confirm order. Missing required information: {', '.join(missing)}.",
                "missing_fields": missing,
            }
            state["tool_name"] = "confirm_order"
            state["tool_result"] = result
            state["response"] = (
                f"⚠️ Cannot confirm order yet. We still need some required information:\n\n"
                f"{format_draft_summary(draft)}\n\n"
                f"Please provide your **{missing[0].replace('_', ' ')}**."
            )
            state["context"] = state["response"]
            return state

        result = commit_confirmed_order(session_id)
        state["tool_name"] = "confirm_order"
        state["tool_result"] = result
        if result.get("ok"):
            resp = _format_confirmed_order_response(result, draft)
            if has_mixed_info and hits:
                kb_text = "\n".join(h["content"].strip() for h in hits[:2])
                resp += f"\n\n---\n### ℹ️ Additional Information:\n{kb_text}"
            state["response"] = resp
            state["context"] = state["response"]
        else:
            state["response"] = f"❌ Order placement failed: {result.get('error', 'Database error')}. Please try again."
            state["context"] = state["response"]
        return state

    # 5. Ongoing Draft Flow: Item Selection, Guided Upselling, & Details Collection
    calc = calculate_draft_totals(draft)
    context_lines.append(format_draft_summary(draft))

    if not draft.get("items"):
        draft["stage"] = "selecting_items"
        context_lines.append("\nCustomer has not added any items yet. Ask what meal they would like to order.")
    elif not draft.get("upsell_offered") and not draft.get("upsell_declined"):
        suggestions = get_upsell_suggestions(draft)
        if suggestions.get("needs_upsell"):
            draft["stage"] = "offering_extras"
            draft["upsell_offered"] = True

            offer_parts = []
            if suggestions.get("suggest_combo"):
                offer_parts.append("Combo upgrade (+50 EGP for French fries and a soft drink)")
            if suggestions.get("suggest_drink"):
                offer_parts.append("Cold drinks (Soft drink 25 EGP, Mineral water 10 EGP)")
            if suggestions.get("suggest_sauce"):
                offer_parts.append("Sauces (Garlic dip 15 EGP, BBQ 25 EGP, Ranch 15 EGP, Sweet Chili 15 EGP, Cheddar 35 EGP)")

            context_lines.append(
                f"\n💡 Guided Upselling Stage:\n"
                f"Present the current draft order to the customer. Then ask if they would like to add any extras before proceeding:\n"
                f"- " + "\n- ".join(offer_parts) + "\n"
                f"(If they say 'no' or decline, we will proceed directly to fulfillment details. Do NOT pressure the customer)."
            )
            state["tool_name"] = "order_upsell"
            state["tool_result"] = {"ok": True, "draft": draft, "calc": calc, "stage": "offering_extras"}
            state["context"] = "\n\n".join(context_lines)
            return state
        else:
            draft["stage"] = "collecting_details"

    # 6. Sequential details collection
    missing = get_missing_fields(draft)
    if missing:
        draft["stage"] = "collecting_details"
        field_names = {
            "order_type": "Order Type (Delivery, Pickup from branch, or Dine-in)",
            "customer_name": "Customer Name",
            "customer_phone": "Phone Number",
            "delivery_address": "Full Delivery Address (Area, Street, Building, Apartment)",
            "pickup_branch": f"Pickup Branch (e.g., Mohandessin, Mokattam, Sheraton, Glim, Mandara, Smouha)",
            "table_number": "Table Number",
            "payment_method": "Payment Method (Cash or Visa)",
        }
        first_missing = missing[0]
        context_lines.append(f"\nNext required information to ask for: {field_names.get(first_missing, first_missing)}. Ask for this field clearly.")
    else:
        draft["stage"] = "awaiting_confirmation"
        context_lines.append(
            "\nAll required order details are complete! Present the final order summary with itemized prices, "
            "combo upgrades, destination, payment method, and final total in EGP. "
            "Ask the customer to explicitly confirm their order ('confirm' / 'yes').\n"
            "CRITICAL: Do NOT state that the order has been placed or invent an order code yet. "
            "The order is NOT confirmed until the customer replies to confirm."
        )

    state["tool_name"] = "order_draft"
    state["tool_result"] = {
        "ok": True,
        "draft": draft,
        "calc": calc,
        "stage": draft.get("stage"),
        "missing_fields": missing,
    }
    state["context"] = "\n\n".join(context_lines)
    return state

def llm_node(state: AgentState) -> AgentState:
    """Invokes Google Gemini with the grounded context prepared by RAG or order tools."""
    from app.services.agent import reply

    if state.get("response"):
        session_id = state.get("session_id", "default")
        message = state.get("message", "")
        hist = get_history(session_id)
        if message and state.get("response"):
            hist.append({"role": "user", "content": message})
            hist.append({"role": "assistant", "content": state["response"]})
        state["history"] = hist
        return state

    session_id = state.get("session_id", "default")
    message = state.get("message", "")
    context = state.get("context", "")
    response = reply(session_id=session_id, user_message=message, context=context)

    # Hallucination guard: intercept fake order numbers if LLM hallucinates confirmation without DB commit
    draft = get_draft(session_id)
    if not draft.get("confirmed_order_code") and (
        "ORD-" in response or "order has been placed" in response.lower() or "تم تأكيد طلبك" in response
    ):
        summary = format_draft_summary(draft)
        response = (
            f"{summary}\n\n"
            f"Please reply **confirm** (or **yes**) to place your order!"
        )
        hist = get_history(session_id)
        if hist and hist[-1].get("role") == "assistant":
            hist[-1]["content"] = response

    state["response"] = response
    state["history"] = get_history(session_id)
    return state

def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("router", router_node)
    graph.add_node("rag", rag_node)
    graph.add_node("order", order_tool_node)
    graph.add_node("llm", llm_node)

    graph.set_entry_point("router")

    graph.add_conditional_edges(
        "router",
        lambda state: state["intent"],
        {
            "RAG": "rag",
            "TOOLS": "order",
        },
    )

    graph.add_edge("rag", "llm")
    graph.add_edge("order", "llm")
    graph.add_edge("llm", END)

    return graph.compile()

_graph = build_graph()

def run(session_id: str, message: str) -> dict:
    """Main workflow entry point for user message execution."""
    return _graph.invoke({
        "session_id": session_id,
        "message": message,
    })