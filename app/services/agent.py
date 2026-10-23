from config import config
import logging
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Modular Provider State (Bedrock Primary, Gemini Automatic Fallback)
_bedrock_client = None
_bedrock_cooldown_until: float = 0.0
_bedrock_permanently_unavailable: bool = False
_bedrock_auth_retry_after: float = 0.0
_bedrock_last_skip_reason: str = ""
_last_provider_used: str = "none"

_gemini_client = None
_gemini_mock_injected: bool = False
_quota_exhausted = False

def get_bedrock_client():
    """Lazily initialize and reuse Amazon Bedrock Runtime client with fail-fast timeout and 1 attempt."""
    global _bedrock_client
    if _bedrock_client is None:
        import boto3
        from botocore.config import Config as BotoConfig

        region = getattr(config, "AWS_REGION", "eu-north-1") or "eu-north-1"
        timeout = int(getattr(config, "BEDROCK_TIMEOUT", 10) or 10)
        boto_cfg = BotoConfig(
            connect_timeout=min(5, timeout),
            read_timeout=timeout,
            retries={"max_attempts": 1, "mode": "standard"},
        )
        _bedrock_client = boto3.client("bedrock-runtime", region_name=region, config=boto_cfg)
    return _bedrock_client

def set_bedrock_client(client: Any = None):
    """Set or override Bedrock Runtime client (useful for testing and fallback simulation)."""
    global _bedrock_client, _bedrock_cooldown_until, _bedrock_permanently_unavailable, _bedrock_auth_retry_after, _bedrock_last_skip_reason
    _bedrock_client = client
    _bedrock_cooldown_until = 0.0
    _bedrock_permanently_unavailable = False
    _bedrock_auth_retry_after = 0.0
    _bedrock_last_skip_reason = ""

def reset_provider_state():
    """Reset provider circuit-breaker and quota state (useful for testing)."""
    global _bedrock_cooldown_until, _bedrock_permanently_unavailable, _bedrock_auth_retry_after, _quota_exhausted, _last_provider_used, _gemini_mock_injected, _bedrock_last_skip_reason
    _bedrock_cooldown_until = 0.0
    _bedrock_permanently_unavailable = False
    _bedrock_auth_retry_after = 0.0
    _quota_exhausted = False
    _last_provider_used = "none"
    _gemini_mock_injected = False
    _bedrock_last_skip_reason = ""

def get_last_provider_used() -> str:
    """Return the provider name ('bedrock', 'gemini', or 'deterministic_fallback') used on the most recent LLM call."""
    return _last_provider_used

def get_gemini_client():
    """Lazily initialize Google Gen AI SDK client with single attempt and fail-fast timeout.
    Does not crash on import or when GEMINI_API_KEY is not yet configured.
    """
    global _gemini_client
    if _gemini_client is None:
        api_key = getattr(config, "GEMINI_API_KEY", "") or ""
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is missing. Please set it in your .env file.")
        from google import genai
        from google.genai import types
        try:
            http_options = types.HttpOptions(
                timeout=10000,
                retry_options=types.HttpRetryOptions(attempts=1),
            )
            _gemini_client = genai.Client(api_key=api_key, http_options=http_options)
        except Exception:
            _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client

def set_gemini_client(client: Any = None):
    """Set or override Gemini client (useful for mock testing)."""
    global _gemini_client, _quota_exhausted, _gemini_mock_injected
    _gemini_client = client
    _gemini_mock_injected = (client is not None)
    if client is not None:
        _quota_exhausted = False

# Backward-compatible aliases
get_client = get_gemini_client
set_client = set_gemini_client

# In-memory conversation state keyed by session ID.
_conversations: dict[str, list] = {}

def get_history(session_id: str) -> list:
    if session_id not in _conversations:
        _conversations[session_id] = []
        try:
            from flask import has_app_context
            if has_app_context():
                from app.models.chat import ChatMessage
                # Load persisted conversation messages chronologically from SQLite
                messages = (
                    ChatMessage.query.filter_by(session_id=session_id)
                    .order_by(ChatMessage.created_at.asc())
                    .all()
                )
                if messages:
                    # If the latest record is an unreplied user message (created right before run),
                    # omit it so the restored history contains only completed past turns and avoids prompt duplication
                    if messages[-1].role == "user":
                        messages = messages[:-1]
                    # Keep recent conversation turns to prevent context window saturation
                    for m in messages[-20:]:
                        _conversations[session_id].append({
                            "role": m.role,
                            "content": m.content,
                        })
        except Exception:
            pass
    return _conversations[session_id]

def clear_history(session_id: str) -> None:
    """Clear in-memory conversation history for a session."""
    if session_id in _conversations:
        del _conversations[session_id]

_SYSTEM_PROMPT = (
    "## 1. Role\n"
    "You are a professional, courteous, and efficient restaurant ordering and customer service AI assistant. "
    "You assist customers with menu inquiries, dish recommendations, branch locations, working hours, and taking complete food orders in their preferred language (Arabic or English).\n\n"
    "## 2. Task\n"
    "1. MENU & INFORMATION: Present menu items and restaurant information accurately with exact prices in EGP and itemized inclusions.\n"
    "2. RECOMMENDATIONS: Provide personalized meal recommendations based on customer preferences, tastes, or dietary questions.\n"
    "3. GUIDED UPSELLING: Conduct guided upselling (offering combo upgrades, drinks, and sauces) after items are selected, respecting customer choices immediately without pressure.\n"
    "4. DETAIL COLLECTION: Collect all required fulfillment details (Delivery, Pickup, Dine-in) one missing detail at a time while remembering previously provided information.\n"
    "5. ORDER SUMMARY & CONFIRMATION: Present complete, itemized final order summaries and request explicit customer confirmation before any order can be submitted.\n"
    "6. GENERAL INQUIRIES: Answer questions regarding operating hours, branches, contact details, and policies using verified information.\n\n"
    "## 3. Context\n"
    "You operate within a restaurant management system. Authoritative menu items, prices, branch locations, operating hours, and active order draft details are maintained by backend services and database records.\n"
    "- When runtime context or retrieved knowledge is provided, treat it as the authoritative single source of truth.\n"
    "- If information requested by the customer is not present in the provided context or knowledge base, politely state that you do not have that information instead of guessing.\n"
    "- All draft calculations, combo fees, discounts, and order persistence are handled by backend transaction tools.\n\n"
    "## 4. Constraints\n"
    "- Authoritative Data Only: Use ONLY factual information from the provided context. Never invent products, secret recipes, prices, discounts, or delivery areas.\n"
    "- No Premature or Hallucinated Confirmations: NEVER state that an order has been placed, confirmed, or recorded, and NEVER generate a fake order code (such as ORD-XXXXX) unless the provided context explicitly confirms that the order was committed to the database with that order code.\n"
    "- Required Information Integrity:\n"
    "  * Delivery: Requires Customer Name, Phone Number, Full Delivery Address (area, street, building, apartment/floor), and Payment Method (Cash or Visa).\n"
    "  * Pickup: Requires Customer Name, Phone Number, Selected Pickup Branch, and Payment Method (Cash or Visa). Never ask for a delivery address for pickup.\n"
    "  * Dine-in: Requires Customer Name, Phone Number, Table Number, and Payment Method (Cash or Visa). Never ask for a delivery address or branch for dine-in.\n"
    "- Step-by-Step Questioning: Ask for only ONE missing required detail at a time to keep conversation smooth and natural.\n"
    "- Arithmetic Integrity: Always use prices and totals provided in the context; never calculate or estimate totals independently.\n"
    "- Clean Output Guard: Never output internal reasoning, chain-of-thought, or analysis tags (such as <think>, 'Thinking Process:', or 'Plan:'). Output ONLY the clean, final customer-facing response.\n"
    "- Markdown Formatting: Output clean, standard Markdown with clean line breaks (###, ####, **, *). Never escape Markdown characters with backslashes (never write \\### or \\**).\n\n"
    "## 5. Examples\n\n"
    "### Example 1 — Menu Presentation\n"
    "User: \"Can I see the menu?\"\n"
    "Assistant:\n"
    "### 📋 Our Menu\n\n"
    "#### 🍗 Meals\n\n"
    "* **Basmatio Rice Meal — 105 EGP**\n"
    "  * Includes: Seasoned basmati rice, crispy chicken strips pieces, coleslaw salad.\n"
    "  * Combo upgrade: +50 EGP for fries and a drink.\n"
    "* **Quarter Broasted Chicken — 135 EGP**\n"
    "  * Includes: Broasted chicken thigh, French fries, fresh bun, small garlic dip, ketchup.\n"
    "  * Combo upgrade: +50 EGP for fries and a drink.\n"
    "* **3-Piece Chicken Strips Meal — 150 EGP**\n"
    "  * Includes: Three crispy chicken strips, French fries, fresh bun, garlic dip.\n"
    "  * Combo upgrade: +50 EGP for fries and a drink.\n"
    "* **Crispy Chicken Fatta — 160 EGP**\n"
    "  * Includes: Seasoned basmati rice, crispy chicken strips, coleslaw salad, crispy toasted bread.\n"
    "  * Combo upgrade: +50 EGP for fries and a drink.\n"
    "* **5-Piece Chicken Strips Meal — 205 EGP**\n"
    "  * Includes: Five crispy chicken strips, French fries, fresh bun, garlic dip.\n"
    "  * Combo upgrade: +50 EGP for fries and a drink.\n"
    "* **Break Meal — 235 EGP**\n"
    "  * Includes: Half broasted chicken, French fries, fresh bun, garlic dip, coleslaw salad, ketchup.\n"
    "  * Combo upgrade: +50 EGP for fries and a drink.\n\n"
    "#### ➕ Add-ons\n\n"
    "* **Extra Chicken Strip** — 35 EGP\n"
    "* **French Fries** — 35 EGP\n"
    "* **Basmati Rice** — 25 EGP\n"
    "* **Coleslaw** — 15 EGP\n"
    "* **Large Garlic Dip** — 15 EGP\n"
    "* **Kaiser Bun** — 5 EGP\n\n"
    "#### 🥫 Sauces\n\n"
    "* **Garlic Dip** — 15 EGP\n"
    "* **BBQ Sauce** — 25 EGP\n"
    "* **Ranch Sauce** — 15 EGP\n"
    "* **Sweet Chili Sauce** — 15 EGP\n"
    "* **Cheddar Cheese Sauce** — 35 EGP\n\n"
    "#### 🥤 Drinks\n\n"
    "* **Soft Drink** — 25 EGP\n"
    "* **Mineral Water** — 10 EGP\n\n"
    "#### 🍟 Extras\n\n"
    "* **Ribbon Fries** — 25 EGP\n\n"
    "### Example 2 — Guided Upselling\n"
    "User: \"I want 1 Break Meal.\"\n"
    "Assistant:\n"
    "I have added **Break Meal** (235 EGP) to your order.\n"
    "Would you like to upgrade to a combo (+50 EGP for French fries and a drink), or add any cold drinks or sauces?\n\n"
    "### Example 3 — Detail Collection\n"
    "User: \"No thanks, delivery please.\"\n"
    "Assistant:\n"
    "Certainly! May I please have your name for the delivery order?\n\n"
    "### Example 4 — Order Summary & Confirmation\n"
    "User: \"Cash payment.\"\n"
    "Assistant:\n"
    "### 🧾 Order Summary\n\n"
    "* **Order Type**: 🚀 Delivery\n"
    "* **Customer Name**: Ziad El Sherif\n"
    "* **Phone Number**: 01011223344\n"
    "* **Delivery Address**: Nasr City, Abbas El Akkad Street\n"
    "* **Payment Method**: Cash\n\n"
    "#### 🛒 Items:\n"
    "* **Break Meal** x1 — 235 EGP\n\n"
    "**Total Amount**: 235 EGP\n\n"
    "Would you like to confirm this order? Please reply with **confirm** to place your order!\n\n"
    "## 6. Notes\n"
    "- Professional Tone: Always reply in clear, helpful, and natural English.\n"
    "- Pacing & Hospitality: Maintain a polite, welcoming, and hospitable tone.\n"
    "- Ambiguity Handling: If a customer request is vague, ask a targeted clarifying question rather than guessing.\n"
    "- Lifecycle Sequence: The workflow strictly follows: selecting_items → offering_extras → collecting_details → awaiting_confirmation → confirmed."
)

def get_system_prompt(context: str = "") -> str:
    """Return the structured system prompt, cleanly incorporating dynamic runtime context into Section 3."""
    if not context or not context.strip():
        return _SYSTEM_PROMPT

    context_block = (
        "## 3. Context\n"
        "### Authoritative Runtime Data:\n"
        f"{context.strip()}\n"
    )
    if "## 3. Context\n" in _SYSTEM_PROMPT:
        return _SYSTEM_PROMPT.replace("## 3. Context\n", context_block, 1)

    return f"{_SYSTEM_PROMPT}\n\n## Additional Context\n{context.strip()}"

def _strip_reasoning(text: str) -> str:
    """Remove reasoning text and clean up the final response."""
    default = "I'm here to help with your restaurant questions."
    if not text or not text.strip():
        return default

    # Remove <think> and <thought> blocks
    text = re.sub(
        r"<(think|thought)>.*?</\1>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )

    # Keep only the final answer if a marker exists
    text = re.sub(
        r"^.*?(?:final (?:customer )?response|customer response|final answer):\s*",
        "",
        text,
        count=1,
        flags=re.IGNORECASE | re.DOTALL
    )

    # Remove common reasoning headers at the beginning
    text = re.sub(
        r"^\s*(?:thinking process|thought process|thinking:|thought:|internal reasoning)\s*\n?",
        "",
        text,
        count=1,
        flags=re.IGNORECASE
    )

    # Fix escaped Markdown characters
    text = re.sub(r"\\+([#*_\-\[\]()])", r"\1", text)

    # Improve Markdown spacing
    text = re.sub(r"(?<!\n)\s+(#{2,6}\s+)", r"\n\n\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip() or default

def _format_bedrock_messages(history: list, user_message: str) -> list:
    """Format conversation history into valid alternating user/assistant messages for Bedrock Converse API."""
    raw_msgs = []
    for msg in history[-20:]:
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        role = "assistant" if msg.get("role") == "assistant" else "user"
        raw_msgs.append({"role": role, "content": content})

    raw_msgs.append({"role": "user", "content": user_message})

    # Merge consecutive messages with identical roles and guarantee the sequence starts with "user"
    merged = []
    for m in raw_msgs:
        if not merged:
            if m["role"] == "assistant":
                continue
            merged.append({"role": "user", "content": [{"text": m["content"]}]})
        elif merged[-1]["role"] == m["role"]:
            merged[-1]["content"][0]["text"] += f"\n\n{m['content']}"
        else:
            merged.append({"role": m["role"], "content": [{"text": m["content"]}]})

    if not merged:
        merged.append({"role": "user", "content": [{"text": user_message}]})
    return merged

def _reply_bedrock(session_id: str, user_message: str, system_prompt: str, history: list) -> Optional[str]:
    """Attempt to generate a response using Amazon Bedrock Runtime Converse API.
    Returns the response text on success, or None if Bedrock is unavailable, throttled, or fails
    so that the caller can transparently fall back to Google Gemini without breaking the conversation.
    """
    global _bedrock_cooldown_until, _bedrock_permanently_unavailable, _bedrock_auth_retry_after, _bedrock_last_skip_reason, _bedrock_client

    bedrock_enabled = getattr(config, "BEDROCK_ENABLED", True)
    provider_pref = getattr(config, "LLM_PROVIDER", "bedrock").lower()
    if not bedrock_enabled or provider_pref == "gemini":
        _bedrock_last_skip_reason = "configured_gemini"
        return None

    # Fast circuit-breaker check to avoid repeatedly calling a provider known to be unavailable or throttled
    now = time.monotonic()
    if _bedrock_permanently_unavailable:
        if now < _bedrock_auth_retry_after:
            remaining_s = _bedrock_auth_retry_after - now
            _bedrock_last_skip_reason = "bedrock_auth_failure"
            logger.info(
                "provider=bedrock status=skipped reason=auth_error_cooldown remaining_cooldown_s=%.1f fallback=gemini",
                remaining_s,
            )
            return None
        else:
            # Recovery: Auth error cooldown elapsed, allow Bedrock retry
            _bedrock_permanently_unavailable = False
            logger.info("provider=bedrock status=recovering reason=auth_cooldown_expired")

    if now < _bedrock_cooldown_until:
        remaining_s = _bedrock_cooldown_until - now
        _bedrock_last_skip_reason = "bedrock_cooldown"
        logger.info(
            "provider=bedrock status=skipped reason=active_cooldown remaining_cooldown_s=%.1f fallback=gemini",
            remaining_s,
        )
        return None

    model_id = getattr(config, "BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0") or "amazon.nova-lite-v1:0"
    token_limit = min(max(int(getattr(config, "AGENT_MAX_TOKENS", 1024) or 1024), 256), 2048)
    temperature = float(getattr(config, "AGENT_TEMPERATURE", 0.3))
    cooldown_sec = int(getattr(config, "BEDROCK_COOLDOWN_SECONDS", 60) or 60)

    t_start = time.perf_counter()
    try:
        client = _bedrock_client if _bedrock_client is not None else get_bedrock_client()
        bedrock_messages = _format_bedrock_messages(history, user_message)

        resp = client.converse(
            modelId=model_id,
            system=[{"text": system_prompt}],
            messages=bedrock_messages,
            inferenceConfig={
                "maxTokens": token_limit,
                "temperature": temperature,
            },
        )
        latency_ms = int((time.perf_counter() - t_start) * 1000)
        output_msg = (resp or {}).get("output", {}).get("message", {})
        content_blocks = output_msg.get("content") or []
        texts = [blk.get("text", "") for blk in content_blocks if isinstance(blk, dict) and blk.get("text")]
        response_text = "\n".join(texts).strip()
        if response_text:
            logger.info(
                "provider=bedrock model=%s status=success latency_ms=%d",
                model_id,
                latency_ms,
            )
            return response_text

        logger.warning(
            "provider=bedrock status=error error_type=EmptyResponse fallback=gemini latency_ms=%d",
            latency_ms,
        )
        _bedrock_last_skip_reason = "bedrock_fallback"
        return None

    except Exception as exc:
        latency_ms = int((time.perf_counter() - t_start) * 1000)
        err_name = type(exc).__name__
        resp_dict = getattr(exc, "response", None) or {}
        err_code = resp_dict.get("Error", {}).get("Code", err_name) if isinstance(resp_dict, dict) else err_name
        err_str = str(exc).lower()

        logger.warning(
            "provider=bedrock status=error error_type=%s fallback=gemini latency_ms=%d",
            err_code,
            latency_ms,
        )
        _bedrock_last_skip_reason = "bedrock_fallback"

        # Classify permanent vs transient errors so we don't repeatedly block future turns
        permanent_codes = (
            "AccessDeniedException",
            "UnrecognizedClientException",
            "InvalidSignatureException",
            "NoCredentialsError",
            "PartialCredentialsError",
            "ResourceNotFoundException",
        )
        if err_code in permanent_codes or any(k in err_str for k in ("accessdenied", "not authorized", "no credentials", "invalid model identifier")):
            _bedrock_permanently_unavailable = True
            _bedrock_auth_retry_after = time.monotonic() + 300.0
            logger.warning("[BEDROCK FALLBACK] Bedrock unavailable (%s); entering auth cooldown (300s) and switching to Gemini.", err_code)
        else:
            _bedrock_cooldown_until = time.monotonic() + cooldown_sec
            logger.warning("[BEDROCK FALLBACK] Bedrock error/throttled (%s); entering %ds cooldown and switching to Gemini.", err_code, cooldown_sec)
        return None

def _reply_gemini(session_id: str, user_message: str, system_prompt: str, history: list, context: str = "", fallback_reason: str = "bedrock_fallback") -> str:
    """Generate a response using Google Gemini (automatic fallback when Bedrock is unavailable)."""
    global _quota_exhausted, _last_provider_used

    api_key = getattr(config, "GEMINI_API_KEY", "")
    model_name = getattr(config, "GEMINI_MODEL", "gemini-2.5-flash")
    token_limit = max(getattr(config, "AGENT_MAX_TOKENS", 2048) or 2048, 2048)

    # If client has been injected via set_gemini_client, use it even if api_key is blank (test mocks)
    global _gemini_client
    injected_client = _gemini_client

    if not api_key and injected_client is None:
        _last_provider_used = "deterministic_fallback"
        logger.info(
            "provider=deterministic_fallback status=success reason=%s missing_gemini_api_key=true",
            fallback_reason,
        )
        if context and context.strip():
            fallback_text = context.strip()
        else:
            fallback_text = (
                "Welcome to our restaurant! How can I help you today? "
                "You can ask to view our menu, get meal recommendations, or start a delivery or pickup order."
            )
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": fallback_text})
        return fallback_text

    # If quota was already exhausted in this session, return grounded context or graceful fallback immediately
    if _quota_exhausted and injected_client is None:
        _last_provider_used = "deterministic_fallback"
        logger.info(
            "provider=deterministic_fallback status=success reason=%s quota_exhausted=true",
            fallback_reason,
        )
        if context and context.strip():
            fallback_text = context.strip()
        else:
            fallback_text = (
                "Sorry, our AI service is currently experiencing high demand. "
                "Please try again in a moment, or call 16099 to place your order directly."
            )
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": fallback_text})
        return fallback_text

    try:
        from google import genai
        from google.genai import types, errors
    except ImportError:
        return "Please install google-genai: pip install google-genai"

    # Convert conversation history into Gemini format
    contents = []
    for msg in history[-20:]:
        if msg.get("content"):
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=msg["content"])]
                )
            )

    # Add the current user message
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_message)]
        )
    )

    # Configure Gemini
    gen_config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=config.AGENT_TEMPERATURE,
        max_output_tokens=token_limit,
    )

    client = injected_client if injected_client is not None else get_gemini_client()
    response_text = ""
    last_error = None
    t_start = time.perf_counter()

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=gen_config,
        )
        latency_ms = int((time.perf_counter() - t_start) * 1000)
        response_text = response.text or ""
        if response_text:
            _last_provider_used = "gemini"
            logger.info(
                "provider=gemini model=%s status=success latency_ms=%d reason=%s",
                model_name,
                latency_ms,
                fallback_reason,
            )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - t_start) * 1000)
        last_error = exc
        err_name = type(exc).__name__
        resp_dict = getattr(exc, "response", None) or {}
        err_code = resp_dict.get("Error", {}).get("Code", err_name) if isinstance(resp_dict, dict) else err_name
        logger.warning(
            "provider=gemini model=%s status=error error_type=%s latency_ms=%d fallback=deterministic",
            model_name,
            err_code,
            latency_ms,
        )
        err_str = str(exc).lower()
        if "quota" in err_str or "429" in err_str or "resource_exhausted" in err_str:
            _quota_exhausted = True

    # Handle unsuccessful requests gracefully without exposing raw API errors
    if not response_text:
        _last_provider_used = "deterministic_fallback"
        logger.info(
            "provider=deterministic_fallback status=success reason=%s",
            fallback_reason,
        )
        err_str = str(last_error or "").lower()
        if "quota" in err_str or "429" in err_str or "resource_exhausted" in err_str:
            response_text = (
                "Sorry, our AI service is currently experiencing high demand. "
                "Please try again in a moment, or call 16099 to place your order directly."
            )
        elif "503" in err_str or "unavailable" in err_str or "overloaded" in err_str:
            response_text = (
                "Sorry, our AI service is temporarily unavailable right now. "
                "Please try again in a moment, or call 16099 for assistance."
            )
        elif context and context.strip():
            response_text = context.strip()
        else:
            response_text = (
                "Sorry, I'm having trouble responding right now. "
                "Please try again in a moment, or contact us at 16099."
            )

    # Save this conversation turn
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": response_text})

    return _strip_reasoning(response_text)

def reply(session_id: str, user_message: str, context: str = "") -> str:
    """Generate customer-facing conversational response with Amazon Bedrock as primary
    and Google Gemini as automatic fallback.
    """
    global _last_provider_used, _gemini_client, _gemini_mock_injected, _bedrock_last_skip_reason
    history = get_history(session_id)
    system_prompt = get_system_prompt(context)

    # Price inquiry fast-path before invoking external LLMs
    from app.services.tools import query_price_info
    order_action_verbs = ("order", "place an order", "i want to order", "اطلب", "عايز اطلب", "عاوز اطلب", "ضيف")
    is_order_command = any(v in user_message.lower() for v in order_action_verbs)
    has_order_context = "Current Order Draft" in system_prompt or "Next required information" in system_prompt
    if not is_order_command and not has_order_context:
        result = query_price_info(user_message)
        if result.get("ok"):
            answer = result["text"]
            _last_provider_used = "deterministic_tool"
            history.append({"role": "user", "content": user_message})
            history.append({"role": "assistant", "content": answer})
            return answer

    # 1. Primary Provider: Amazon Bedrock
    # Run Bedrock unless a test explicitly injected a Gemini mock client without a Bedrock mock client
    if not _gemini_mock_injected or _bedrock_client is not None:
        bedrock_text = _reply_bedrock(session_id, user_message, system_prompt, history)
        if bedrock_text:
            _last_provider_used = "bedrock"
            cleaned = _strip_reasoning(bedrock_text)
            history.append({"role": "user", "content": user_message})
            history.append({"role": "assistant", "content": cleaned})
            return cleaned

    # 2. Automatic Fallback Provider: Google Gemini
    fallback_reason = _bedrock_last_skip_reason or "bedrock_fallback"
    return _reply_gemini(session_id, user_message, system_prompt, history, context=context, fallback_reason=fallback_reason)
