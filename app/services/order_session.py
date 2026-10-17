"""
Order Session & Draft Management Service.
Maintains in-memory conversational draft order state per session.
Tracks order items, combo upgrades, order type (delivery, pickup, dine_in),
customer details (name, phone), destination details (address, pickup_branch, table_number),
and payment_method (Cash, Visa).

Enforces strict field requirements before final confirmation:
- Delivery: customer_name, customer_phone, delivery_address, payment_method
- Pickup: customer_name, customer_phone, pickup_branch, payment_method
- Dine-in: customer_name, customer_phone, table_number, payment_method
"""

import json
import re
from typing import Any, Optional
from flask import has_app_context
from app.models.product import Product
from app.models.customer import Customer
from app.models.order import Order
from app.models.chat import ChatSession
from app.models.base import db
from app.services.tools import create_order, find_or_create_customer, _with_app_context

# Known branches from knowledge/details.md (authoritative English names)
AVAILABLE_BRANCHES = [
    "Mohandessin Branch",
    "Mokattam Branch",
    "Sheraton Branch",
    "Glim Branch",
    "Mandara Branch",
    "Camp Caesar Branch",
    "Smouha Branch 1",
    "Smouha Branch 2",
    "Bahary Branch",
    "Sidi Bishr Branch",
    "Mahrousa Branch",
]

# Branch aliases mapping English & Arabic expressions to canonical branch names
BRANCH_ALIASES = {
    # English names & shorthands
    "mohandessin": "Mohandessin Branch",
    "mohandessin branch": "Mohandessin Branch",
    "mokattam": "Mokattam Branch",
    "mokattam branch": "Mokattam Branch",
    "sheraton": "Sheraton Branch",
    "sheraton branch": "Sheraton Branch",
    "glim": "Glim Branch",
    "glim branch": "Glim Branch",
    "radio street": "Glim Branch",
    "mandara": "Mandara Branch",
    "mandara branch": "Mandara Branch",
    "camp caesar": "Camp Caesar Branch",
    "camp caesar branch": "Camp Caesar Branch",
    "camp": "Camp Caesar Branch",
    "smouha 1": "Smouha Branch 1",
    "smouha branch 1": "Smouha Branch 1",
    "smouha 2": "Smouha Branch 2",
    "smouha branch 2": "Smouha Branch 2",
    "smouha": "Smouha Branch 1",
    "bahary": "Bahary Branch",
    "bahary branch": "Bahary Branch",
    "sidi bishr": "Sidi Bishr Branch",
    "sidi bishr branch": "Sidi Bishr Branch",
    "mahrousa": "Mahrousa Branch",
    "mahrousa branch": "Mahrousa Branch",
    # Arabic names & aliases
    "المهندسين": "Mohandessin Branch",
    "فرع المهندسين": "Mohandessin Branch",
    "المقطم": "Mokattam Branch",
    "فرع المقطم": "Mokattam Branch",
    "الشيراتون": "Sheraton Branch",
    "فرع الشيراتون": "Sheraton Branch",
    "شيراتون": "Sheraton Branch",
    "جليم": "Glim Branch",
    "فرع جليم": "Glim Branch",
    "شارع الاذاعة": "Glim Branch",
    "شارع الإذاعة": "Glim Branch",
    "المندرة": "Mandara Branch",
    "فرع المندرة": "Mandara Branch",
    "مندرة": "Mandara Branch",
    "كامب شيزار": "Camp Caesar Branch",
    "فرع كامب شيزار": "Camp Caesar Branch",
    "كامب": "Camp Caesar Branch",
    "سموحة 1": "Smouha Branch 1",
    "فرع سموحة 1": "Smouha Branch 1",
    "سموحة 2": "Smouha Branch 2",
    "فرع سموحة 2": "Smouha Branch 2",
    "سموحة": "Smouha Branch 1",
    "فرع سموحة": "Smouha Branch 1",
    "بحري": "Bahary Branch",
    "فرع بحري": "Bahary Branch",
    "سيدي بشر": "Sidi Bishr Branch",
    "فرع سيدي بشر": "Sidi Bishr Branch",
    "المحروسة": "Mahrousa Branch",
    "فرع المحروسة": "Mahrousa Branch",
    "محروسة": "Mahrousa Branch",
}

# Session drafts store: session_id -> draft_dict
_drafts: dict[str, dict[str, Any]] = {}

def _load_draft_from_db(session_id: str) -> Optional[dict[str, Any]]:
    """Attempt to load persisted draft from SQLite ChatSession table."""
    # Guard against runtime errors if called outside an active Flask request context
    if not has_app_context():
        return None
    try:
        chat_sess = ChatSession.query.filter_by(session_id=session_id).first()
        # Restore draft JSON so cart items survive server restarts or memory cleanup
        if chat_sess and chat_sess.draft_data:
            data = json.loads(chat_sess.draft_data)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return None

def _save_draft_to_db(session_id: str, draft: Optional[dict[str, Any]]) -> None:
    """Persist draft into SQLite ChatSession table."""
    # Ensure database writes only proceed within a valid Flask context
    if not has_app_context():
        return
    try:
        chat_sess = ChatSession.query.filter_by(session_id=session_id).first()
        if chat_sess:
            # Sync in-memory draft directly to the database column for multi-turn durability
            chat_sess.draft_data = json.dumps(draft, ensure_ascii=False) if draft else None
            db.session.commit()
    except Exception:
        # Roll back failed transaction to prevent poisoning the database connection pool
        try:
            db.session.rollback()
        except Exception:
            pass

def get_draft(session_id: str) -> dict[str, Any]:
    """Retrieve or initialize draft order for a session."""
    # Check cache first; if missing in memory, restore from SQLite before initializing empty draft
    if session_id not in _drafts:
        saved = _load_draft_from_db(session_id)
        if saved:
            _drafts[session_id] = saved
        else:
            _drafts[session_id] = {
                "session_id": session_id,
                "order_type": None,          # "delivery", "pickup", "dine_in"
                "customer_name": None,
                "customer_phone": None,
                "delivery_address": None,
                "pickup_branch": None,
                "table_number": None,
                "payment_method": None,      # "Cash", "Visa"
                "items": [],                 # list of item dicts
                "stage": "selecting_items",   # "selecting_items", "offering_extras", "collecting_details", "awaiting_confirmation", "confirmed"
                "upsell_offered": False,     # whether extras have been suggested
                "upsell_declined": False,    # whether customer declined extras
                "confirmed_order_code": None, # Set only once successfully committed
            }
    return _drafts[session_id]

def clear_draft(session_id: str) -> None:
    """Reset draft after successful order placement."""
    if session_id in _drafts:
        del _drafts[session_id]
    _save_draft_to_db(session_id, None)

def _is_negated_preceding(preceding: str) -> bool:
    """Check if the text immediately preceding a matched keyword indicates negation within the local clause."""
    # Split by clause boundaries (punctuation, contrastive conjunctions) to evaluate only the immediate clause
    clause = re.split(r"[,.;!?]|\b(?:but|instead|بس|لكن|بدل)\b", preceding)[-1].strip()
    if not clause:
        return False
    # Negation pattern allowing optional filler words (e.g. 'don't have a', 'not a', 'مش معايا')
    neg_pat = r"\b(?:no|not|don'?t|never|without|hardly|معيش|مش|لا|مفيش|بدون|من\s*غير|بلاش)\b(?:\s+\w+){0,3}\s*$"
    return bool(re.search(neg_pat, clause, re.IGNORECASE))

def _detect_fulfillment_type(text: str) -> Optional[str]:
    """
    Detect fulfillment type (delivery, pickup, dine_in) from customer text.
    Handles negation (e.g., 'no delivery, pickup please'), avoids partial-word collisions
    (e.g., 'vegetable' -> dine_in), and ignores question/inquiry comparisons.
    """
    t = (text or "").lower().strip()
    if not t:
        return None

    # Comparative or undecided questions should not prematurely pick a channel
    if ("?" in t or "؟" in t) and re.search(r"\b(?:or|أم|ولا|لو)\b", t):
        return None

    pats = {
        "delivery": [
            r"\b(?:delivery|deliver|delievery|delivry|home\s+delivery)\b",
            r"(?:توصيل|دليفري|على\s*البيت|للمنزل)",
        ],
        "pickup": [
            r"\b(?:pickup|pick\s*up|takeaway|take\s*away)\b",
            r"(?:استلام|من\s*الفرع|تيك\s*اواي|تيك\s*أواي|سفري|هاجي\s*اخده|هعدي\s*اخده)",
        ],
        "dine_in": [
            r"\b(?:dine[- ]?in|dinein|on[- ]?site|eat[- ]?in)\b",
            r"\btable\s*(?:#|number|no\.?|\d+)\b",
            r"\b(?:at\s+the\s+table)\b",
            r"(?:صالة|في\s*المطعم|داخل\s*المطعم|على\s*الطاولة|ترابيزة|طاولة)",
        ],
    }

    detected_positive = set()
    detected_negative = set()

    for channel, regex_list in pats.items():
        for pat in regex_list:
            for m in re.finditer(pat, t):
                start = m.start()
                preceding = t[max(0, start - 35):start]
                if _is_negated_preceding(preceding):
                    detected_negative.add(channel)
                else:
                    detected_positive.add(channel)

    effective = detected_positive - detected_negative
    if len(effective) == 1:
        return next(iter(effective))

    return None

def _detect_payment_method(text: str) -> Optional[str]:
    """
    Detect payment method (Cash, Visa, Vodafone Cash).
    Handles negation (e.g. 'don't have credit card, pay cash'), and distinguishes
    mobile-wallet methods (Vodafone Cash) from physical cash.
    """
    t = (text or "").lower().strip()
    if not t:
        return None

    # 1. Supported Mobile Wallet (Vodafone Cash, Orange Cash, InstaPay)
    wallet_pat = r"\b(?:vodafone\s*cash|orange\s*cash|etisalat\s*cash|smart\s*wallet|instapay)\b|(?:فودافون\s*كاش|اورنج\s*كاش|اتصالات\s*كاش|وي\s*باي|انستاباي|محفظة\s*الكترونية)"
    wallet_match = re.search(wallet_pat, t)
    if wallet_match:
        preceding = t[max(0, wallet_match.start() - 35):wallet_match.start()]
        if not _is_negated_preceding(preceding):
            return "Vodafone Cash"

    # 2. Check Card / Visa vs Cash with negation handling
    card_pat = r"\b(?:credit\s*card|debit\s*card|visa|mastercard|card|credit|debit)\b|(?:فيزا|كارت|بطاقة|ماستركارد)"
    t_no_wallet = re.sub(wallet_pat, " ", t)
    cash_pat = r"\b(?:cash|cash\s*on\s*delivery|cod)\b|(?:كاش|نقد|نقدي|عند\s*الاستلام)"

    card_pos, card_neg = False, False
    cash_pos, cash_neg = False, False

    for m in re.finditer(card_pat, t_no_wallet):
        preceding = t_no_wallet[max(0, m.start() - 35):m.start()]
        if _is_negated_preceding(preceding):
            card_neg = True
        else:
            card_pos = True

    for m in re.finditer(cash_pat, t_no_wallet):
        preceding = t_no_wallet[max(0, m.start() - 35):m.start()]
        if _is_negated_preceding(preceding):
            cash_neg = True
        else:
            cash_pos = True

    effective_card = card_pos and not card_neg
    effective_cash = cash_pos and not cash_neg

    if effective_cash and not effective_card:
        return "Cash"
    if effective_card and not effective_cash:
        return "Visa"

    return None

@_with_app_context
def parse_user_entities(session_id: str, message: str) -> dict[str, Any]:
    """
    Extract fulfillment details from message and update draft:
    - Order type: Delivery / Pickup / Dine-in
    - Phone number: Egyptian 10-11 digit numbers
    - Payment method: Cash / Visa / Vodafone Cash
    - Branch: matches known branches
    - Table: table number / table id
    - Name: name patterns
    - Delivery Address: address patterns
    - Product additions: recognizes menu products + quantity + combo
    """
    draft = get_draft(session_id)
    text = (message or "").strip()
    text_lower = text.lower()
    changes = {}

    # 0. Check for upselling decline or acceptance
    decline_signals = [
        "no", "no thanks", "no thank you", "nope", "nothing", "neither",
        "لا", "لا شكرا", "لا شكراً", "لا تمام", "تمام كده", "مش عايز", "مش عاوز", "كفاية", "بس كده", "لا مش محتاج", "مش محتاج"
    ]
    clean_text = text_lower.strip(" .!?,")
    if (clean_text in decline_signals or any(clean_text.startswith(s + " ") for s in ["no", "no thanks", "لا", "لا شكرا", "لا شكراً"])) and draft.get("items"):
        draft["upsell_declined"] = True
        draft["upsell_offered"] = True
        draft["stage"] = "collecting_details"
        changes["upsell_declined"] = True

    # Check if customer explicitly opted in to combo upgrade
    combo_signals = [
        "make it combo", "make them combo", "add combo", "combo please", "upgrade to combo", "yes combo", "combo", "with combo",
        "خليهم كومبو", "مع كومبو", "ضيف كومبو", "نعم كومبو", "عايز كومبو", "عاوز كومبو", "كومبو"
    ]
    if any(re.search(rf"\b{re.escape(sig)}\b", text_lower) if " " not in sig else sig in text_lower for sig in combo_signals) and draft.get("items"):
        upgrade_res = upgrade_draft_combos(session_id)
        if upgrade_res.get("upgraded_count", 0) > 0:
            changes["combo_upgraded"] = True

    # 1. Order type extraction: safely handles negation and word boundaries
    detected_type = _detect_fulfillment_type(text)
    if detected_type:
        update_draft(session_id, order_type=detected_type)
        changes["order_type"] = detected_type

    # 2. Payment method: distinguishes Cash, Visa, and mobile wallet methods with negation safety
    detected_payment = _detect_payment_method(text)
    if detected_payment:
        update_draft(session_id, payment_method=detected_payment)
        changes["payment_method"] = detected_payment

    # 3. Phone number: matches Egyptian mobile format (010, 011, 012, 015 followed by 8 digits) with optional +20 country prefix
    phone_match = re.search(r"(?:(?:\+?20)|0)?1[0125]\d{8}\b", text)
    if phone_match:
        phone_val = phone_match.group(0).strip()
        update_draft(session_id, customer_phone=phone_val)
        changes["customer_phone"] = phone_val

    # 4. Table number: extracts table ID for dine-in orders while guarding against phone or price numbers
    table_match = re.search(r"(?:table|ترابيزة|طاولة|طاوله)\s*(?:رقم|number|#)?\s*(\d+|[a-zA-Z]\d*)", text, re.IGNORECASE)
    if not table_match and (draft.get("order_type") == "dine_in" or detected_type == "dine_in"):
        # Standalone short answer like "12", "T12", "A5" when system specifically asked for table number
        m_standalone = re.fullmatch(r"\s*(?:#|no\.?|رقم)?\s*(\d+|[a-zA-Z]\d+)\s*", text, re.IGNORECASE)
        if m_standalone and not phone_match:
            tbl_candidate = m_standalone.group(1).strip()
            # Guard against mistaking long numeric inputs (e.g. phone numbers or money amounts) for table IDs
            if len(tbl_candidate) <= 4:
                table_match = m_standalone
    if table_match:
        tbl = table_match.group(1).strip()
        update_draft(session_id, table_number=tbl)
        changes["table_number"] = tbl

    # 5. Branch selection: validates pickup requests against known restaurant locations
    # Guard: do not set pickup_branch if the user is asking an informational question about branches
    inquiry_markers = ("?", "؟", "what", "which", "where", "how", "list", "show", "can i", "do you", "أين", "فين", "ما هي", "ايه هي", "إيه هي", "كام")
    is_branch_question = any(q in text_lower for q in inquiry_markers) and any(b_kw in text_lower for b_kw in ("branch", "branches", "pickup", "فرع", "فروع", "استلام"))
    if not is_branch_question:
        matched_branch = None
        # Sort aliases by descending length so more specific phrases match first
        for alias, canonical_branch in sorted(BRANCH_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", text_lower) if alias.isascii() else alias in text_lower:
                matched_branch = canonical_branch
                break
        if matched_branch:
            update_draft(session_id, pickup_branch=matched_branch)
            changes["pickup_branch"] = matched_branch

    # Helper: Check segmented compound messages (e.g., "عبدالرحمن احمد - وابورالمياة شارع فتح الله - كاش")
    # Allows customers to provide full details in a single delimited message
    segments = [s.strip() for s in re.split(r"[-–—|\n]+", text) if s.strip()]
    if len(segments) >= 2:
        for seg in segments:
            seg_lower = seg.lower()
            if any(w in seg_lower for w in ["cash", "كاش", "نقد", "نقدي"]):
                continue
            if any(w in seg_lower for w in ["visa", "فيزا"]):
                continue
            if re.search(r"(?:(?:\+?20)|0)?1[0125]\d{8}\b", seg):
                continue
            if "شارع" in seg or "street" in seg_lower or "st." in seg_lower or "وابور" in seg:
                update_draft(session_id, delivery_address=seg)
                changes["delivery_address"] = seg
            order_intent_words = [
                "order", "want", "add", "have", "أطلب", "اطلب", "عاوز", "عايز", "أريد", "اريد", "هاتلي", "طلب",
                "بسمتيو", "بروستد", "ستربس", "بريك", "فتة", "فته", "وجبة", "وجبه", "كومبو", "combo", "meal",
                "delivery", "delievery", "pickup", "dine", "dine-in", "توصيل", "استلام", "صالة", "ترابيزة", "طاولة",
            ]
            seg_has_order = any(w in seg_lower for w in order_intent_words)
            if not seg_has_order and not draft.get("customer_name") and 1 <= len(seg.split()) <= 4 and not any(ch.isdigit() for ch in seg):
                update_draft(session_id, customer_name=seg)
                changes["customer_name"] = seg

    # Refresh draft after segment extraction
    draft = get_draft(session_id)

    # 6. Customer name
    order_stop_words = [
        "delivery", "delievery", "pickup", "dine", "dine-in", "dinein", "dining", "cash", "visa", "order", "want", "menu", "confirm", "yes", "table", "branch",
        "شارع", "street", "عاوز", "عايز", "أطلب", "اطلب", "أريد", "اريد", "توصيل", "استلام", "صالة", "ترابيزة", "طاولة",
        "بسمتيو", "بروستد", "ستربس", "بريك", "فتة", "فته", "وجبة", "وجبه", "كومبو", "combo", "meal", "هاتلي", "مع", "بدون",
        "no", "no thanks", "no thank you", "none", "thanks", "thank you", "لا", "لا شكرا", "لا شكراً", "لا تمام", "تمام", "مش عايز", "مش عاوز", "كفاية", "بس كده", "شكرا", "شكراً",
    ]
    common_menu_names = [
        "basmatio", "basmetio", "cheddar", "cheder", "strips", "broasted", "break", "fatta", "fries", "rice", "coleslaw", "pepsi", "drink", "water",
        "بسمتيو", "شيدر", "بريك", "ستربس", "فتة", "بطاطس", "أرز", "رز", "ثومية", "كول سلو", "باربكيو", "رانش", "سويت تشيلي", "مشروب", "بيبسي", "مياه", "وجبة"
    ]
    if not draft.get("customer_name"):
        # Matches "my name is X", "i'm X", "اسمي X", "أنا X"
        name_match = re.search(r"(?:my name is\s+|my name\s*:\s*|name\s*:\s*|i am\s+|i\'m\s+|اسمي\s+|أنا\s+|انا\s+)([\w\s]{2,25})", text, re.IGNORECASE)
        if name_match:
            cand_name = name_match.group(1).split(",")[0].strip()
            cand_name = re.split(r"(?:\band\b|\bو\b|phone|رقم|cash|visa|كاش|فيزا|address|عنوان|street|شارع)", cand_name, flags=re.IGNORECASE)[0].strip()
            # Filter out common stop words and order phrases
            cand_lower = cand_name.lower()
            if len(cand_name) >= 2 and not any(w in cand_lower for w in order_stop_words) and not any(m in cand_lower for m in common_menu_names):
                update_draft(session_id, customer_name=cand_name)
                changes["customer_name"] = cand_name
        elif not draft.get("customer_name") and (draft.get("order_type") or draft.get("items")):
            # Standalone name answer (e.g. user replies "Abdelrahman" or "كريم")
            words = text.split()
            if 1 <= len(words) <= 3 and len(text) >= 2 and not phone_match and not any(ch.isdigit() for ch in text):
                if not any(w in text_lower for w in order_stop_words) and not any(m in text_lower for m in common_menu_names) and _detect_fulfillment_type(text) is None:
                    # Guard against single-word commands or punctuation
                    if re.match(r"^[\w\s\.\-']+$", text, re.UNICODE):
                        update_draft(session_id, customer_name=text)
                        changes["customer_name"] = text

    # 7. Delivery address (especially if order_type is delivery or message mentions address / street)
    if not draft.get("delivery_address"):
        addr_match = re.search(r"(?:address(?:\s+is)?|عنواني|العنوان|delivery to|deliver to|توصيل\s+إلى|توصيل\s+الي)\s*[:=]?\s*([^\n\r]+)", text, re.IGNORECASE)
        if not addr_match and any(w in text_lower for w in ("شارع", "street", "st.", "st ", "road", "عمارة", "building", "floor", "دور", "شقة", "وابور", "wabour", "apartment", "apt")):
            addr_match = re.search(r"(\d*[\s\w,.\-#]+(?:street|st\.?|شارع|building|عمارة|road|طريق|حي|منطقة|وابور|wabour|apartment|apt|floor|دور|شقة)[\s\w,.\-#]*)", text, re.IGNORECASE)
        if addr_match:
            cand_addr = addr_match.group(1).strip()
            # Clean trailing stop words like 'my name is...', 'phone...', 'cash'
            cand_addr = re.split(r"(?:,\s*)?(?:my name|phone|name:|اسمي|رقم|cash|visa|كاش|فيزا)", cand_addr, flags=re.IGNORECASE)[0].strip(" ,.-")
            if len(cand_addr) >= 3:
                update_draft(session_id, delivery_address=cand_addr)
                changes["delivery_address"] = cand_addr
                # Auto-infer order_type as delivery if not yet set
                if not draft.get("order_type"):
                    update_draft(session_id, order_type="delivery")
                    changes["order_type"] = "delivery"
        elif draft.get("order_type") == "delivery" and not draft.get("delivery_address") and not changes.get("customer_name"):
            # If user is directly answering the address question with a standalone address
            if _detect_fulfillment_type(text) is None and not any(k in text_lower for k in ["order", "menu", "cash", "visa", "confirm", "recommend", "delivery", "delievery", "pickup", "dine", "no thanks", "لا شكرا"]):
                if not any(m in text_lower for m in common_menu_names) and not any(w in text_lower for w in order_stop_words):
                    if len(text) >= 3 and any(ch.isalpha() for ch in text) and not phone_match:
                        update_draft(session_id, delivery_address=text)
                        changes["delivery_address"] = text

    # 8. Product and item additions
    # Check known menu products in DB sorted longest first to avoid partial overlap
    try:
        products = Product.query.filter(Product.is_available == True).all()
        # Aliases mapping for common names, English shorthands, and legacy Arabic names
        product_aliases = {
            # English shorthands
            "break": "Break Meal",
            "break meal": "Break Meal",
            "half chicken": "Break Meal",
            "quarter chicken": "Quarter Broasted Chicken",
            "quarter broasted": "Quarter Broasted Chicken",
            "broasted": "Quarter Broasted Chicken",
            "3 strips": "3-Piece Chicken Strips Meal",
            "strips 3": "3-Piece Chicken Strips Meal",
            "3-piece strips": "3-Piece Chicken Strips Meal",
            "5 strips": "5-Piece Chicken Strips Meal",
            "strips 5": "5-Piece Chicken Strips Meal",
            "5-piece strips": "5-Piece Chicken Strips Meal",
            "strips": "3-Piece Chicken Strips Meal",
            "chicken strips": "3-Piece Chicken Strips Meal",
            "chicken meal": "Quarter Broasted Chicken",
            "chicken meals": "Quarter Broasted Chicken",
            "chicken sandwich": "Quarter Broasted Chicken",
            "chicken sandwiches": "Quarter Broasted Chicken",
            "fatta": "Crispy Chicken Fatta",
            "chicken fatta": "Crispy Chicken Fatta",
            "basmatio": "Basmatio Rice Meal",
            "basmetio": "Basmatio Rice Meal",
            "basmati rice": "Basmati Rice",
            "rice": "Basmati Rice",
            "fries": "French Fries",
            "french fries": "French Fries",
            "packet of fries": "French Fries",
            "extra strip": "Extra Chicken Strip",
            "large garlic": "Large Garlic Dip",
            "garlic dip": "Garlic Dip",
            "garlic": "Garlic Dip",
            "bun": "Kaiser Bun",
            "kaiser bun": "Kaiser Bun",
            "bread": "Kaiser Bun",
            "coleslaw": "Coleslaw",
            "bbq": "BBQ Sauce",
            "bbq sauce": "BBQ Sauce",
            "cheddar": "Cheddar Cheese Sauce",
            "cheder": "Cheddar Cheese Sauce",
            "cheddar sauce": "Cheddar Cheese Sauce",
            "cheese sauce": "Cheddar Cheese Sauce",
            "ranch": "Ranch Sauce",
            "ranch sauce": "Ranch Sauce",
            "sweet chili": "Sweet Chili Sauce",
            "sweet chilli": "Sweet Chili Sauce",
            "pepsi": "Soft Drink",
            "drink": "Soft Drink",
            "soft drink": "Soft Drink",
            "soda": "Soft Drink",
            "water": "Mineral Water",
            "mineral water": "Mineral Water",
            "ribbon fries": "Ribbon Fries",
            # Legacy Arabic aliases mapping to English canonical names
            "وجبة بريك": "Break Meal",
            "بريك": "Break Meal",
            "نصف فرخة": "Break Meal",
            "ربع فرخة": "Quarter Broasted Chicken",
            "ربع فرخة بروستد": "Quarter Broasted Chicken",
            "وجبة ستربس 3 قطع": "3-Piece Chicken Strips Meal",
            "ستربس 3": "3-Piece Chicken Strips Meal",
            "وجبة ستربس 5 قطع": "5-Piece Chicken Strips Meal",
            "ستربس 5": "5-Piece Chicken Strips Meal",
            "وجبة ستربس": "3-Piece Chicken Strips Meal",
            "فتة": "Crispy Chicken Fatta",
            "فتة فراخ": "Crispy Chicken Fatta",
            "بسمتيو": "Basmatio Rice Meal",
            "قطعة ستربس": "Extra Chicken Strip",
            "أرز بسمتي": "Basmati Rice",
            "باكيت بطاطس": "French Fries",
            "بطاطس": "French Fries",
            "ثومية كبير": "Large Garlic Dip",
            "ثومية": "Garlic Dip",
            "عيش كايزر": "Kaiser Bun",
            "كول سلو": "Coleslaw",
            "باربكيو": "BBQ Sauce",
            "شيدر": "Cheddar Cheese Sauce",
            "صوص شيدر": "Cheddar Cheese Sauce",
            "رانش": "Ranch Sauce",
            "سويت تشيلي": "Sweet Chili Sauce",
            "مشروب": "Soft Drink",
            "مياه": "Mineral Water",
            "شريطي فرايز": "Ribbon Fries",
        }
        word_quantities = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "واحد": 1, "واحدة": 1, "واحده": 1,
            "اتنين": 2, "اثنين": 2,
            "تلاتة": 3, "ثلاثة": 3,
            "اربعة": 4, "أربعة": 4,
            "خمسة": 5,
        }
        num_words_pat = r"one|two|three|four|five|واحد|واحدة|واحده|اتنين|اثنين|تلاتة|ثلاثة|اربعة|أربعة|خمسة"
        has_want_to_order = bool(re.search(r"\b(?:want|would like|need|order|buy|get|have)\b.*?\b(?:order|meal|meals|sandwich|sandwiches|food)\b", text_lower))
        order_verbs = [
            "order", "add", "bring me", "give me", "deliver", "want",
            "أطلب", "اطلب", "هاتلي", "ابعتلي", "ضيف", "وصلني", "عاوز", "عايز", "أريد", "اريد"
        ]
        has_order_verb = any(v in text_lower for v in order_verbs)
        has_explicit_qty = bool(re.search(rf"\b(?:\d+|{num_words_pat})\b", text_lower))
        is_in_ordering = draft.get("stage") in ("selecting_items", "collecting_details") and len(draft.get("items", [])) > 0
        products_sorted = sorted(products, key=lambda x: len(x.name), reverse=True)
        matched_spans = []

        # First check DB product names, then aliases, sorted longest first
        targets = [(p.name, p) for p in products_sorted]
        for alias, real_name in product_aliases.items():
            match_prod = next((p for p in products if p.name == real_name), None)
            if match_prod:
                targets.append((alias, match_prod))
        targets.sort(key=lambda t: len(t[0]), reverse=True)

        for target_term, p in targets:
            term_lower = target_term.lower()
            if re.search(r"^[a-z0-9\s]+$", term_lower):
                m_term = re.search(rf"\b{re.escape(term_lower)}\b", text_lower)
                if not m_term:
                    continue
                span = (m_term.start(), m_term.end())
            else:
                if term_lower not in text_lower:
                    continue
                idx = text_lower.find(term_lower)
                span = (idx, idx + len(term_lower))

            # Discard if overlapping with any already matched span
            if any(max(s[0], span[0]) < min(s[1], span[1]) for s in matched_spans):
                continue
            matched_spans.append(span)

            qty = 1
            qty_match = re.search(rf"(?:(\d+)|(?:و\s*)?({num_words_pat}))\s*(?:x|from|of|قطع|قطعة|وجبات|وجبة)?\s*{re.escape(target_term)}", text, re.IGNORECASE)
            if not qty_match:
                qty_match = re.search(rf"{re.escape(target_term)}\s*(?:x|عدد)?\s*(?:(\d+)|(?:و\s*)?({num_words_pat}))", text, re.IGNORECASE)
            if qty_match:
                digit_grp = qty_match.group(1)
                word_grp = qty_match.group(2)
                if digit_grp:
                    try:
                        qty = max(1, int(digit_grp))
                    except Exception:
                        qty = 1
                elif word_grp:
                    qty = word_quantities.get(word_grp.strip().lower(), 1)

            is_combo = bool("combo" in text_lower or "كومبو" in text_lower)
            # Protect against adding items to cart when user is asking an informational question
            inquiry_markers = (
                "?", "؟", "what", "how", "can i see", "do you have", "tell me", "know", "ask", "see",
                "ingredients", "contain", "include", "price", "cost", "details", "comes with",
                "سعر", "اسعار", "أسعار", "بكام", "تكلفة", "مكونات", "يحتوي", "فيه", "عبارة عن",
                "ايه", "إيه", "تفاصيل", "عايز اعرف", "عاوز اعرف", "حابب اعرف", "اسأل عن", "اسال عن", "ممكن اعرف", "بيجي معاه"
            )
            is_inquiry = any(q in text_lower for q in inquiry_markers)
            order_verbs = [
                "order", "add", "bring me", "give me", "deliver",
                "أطلب", "اطلب", "هاتلي", "ابعتلي", "ضيف", "وصلني"
            ]
            has_explicit_order_action = has_want_to_order or any(w in text_lower for w in ["order", "أطلب", "اطلب", "add", "ضيف"])
            is_pure_inquiry = is_inquiry and not has_explicit_order_action
            is_explicit_order = (has_order_verb or has_explicit_qty or is_in_ordering) and not is_pure_inquiry
            if is_explicit_order:
                add_item_to_draft(session_id, product_name=p.name, quantity=qty, is_combo=is_combo)
                changes["added_product"] = p.name
    except Exception:
        pass

    _save_draft_to_db(session_id, draft)
    return changes

def get_missing_fields(draft: dict[str, Any]) -> list[str]:
    """
    Determine which required fields are still missing according to order_type.
    """
    missing = []

    # Order cannot be processed without items
    if not draft.get("items"):
        missing.append("items")

    # Order type dictates destination requirements; prompt for type first if unset
    order_type = draft.get("order_type")
    if not order_type:
        missing.append("order_type")
        return missing

    # Common required contact details for all order types
    if not draft.get("customer_name") and not draft.get("customer_phone"):
        missing.append("customer_name")
    if not draft.get("customer_phone"):
        missing.append("customer_phone")
    if not draft.get("payment_method"):
        missing.append("payment_method")

    # Destination requirements specific to each fulfillment channel
    if order_type == "delivery":
        if not draft.get("delivery_address"):
            missing.append("delivery_address")
    elif order_type == "pickup":
        if not draft.get("pickup_branch"):
            missing.append("pickup_branch")
    elif order_type == "dine_in":
        if not draft.get("table_number"):
            missing.append("table_number")

    return missing

def calculate_draft_totals(draft: dict[str, Any]) -> dict[str, Any]:
    """
    Calculate accurate prices using trusted DB product prices.
    Applies combo upgrade once per item/quantity.
    Returns calculated summary dict.
    """
    items = draft.get("items", [])
    total = 0.0
    item_summaries = []

    for it in items:
        qty = int(it.get("quantity", 1))
        unit = float(it.get("unit_price", 0.0))
        is_combo = bool(it.get("is_combo", False))
        combo_p = float(it.get("combo_price", 0.0)) if is_combo else 0.0
        # Combo fee is added to each individual unit before multiplying by quantity
        line_unit = unit + combo_p
        line_tot = round(line_unit * qty, 2)
        total += line_tot

        combo_label = " (Combo)" if is_combo else ""
        item_summaries.append({
            "name": it.get("product_name"),
            "product_id": it.get("product_id"),
            "quantity": qty,
            "unit_price": unit,
            "is_combo": is_combo,
            "combo_price": combo_p,
            "line_unit_price": line_unit,
            "line_total": line_tot,
            "notes": it.get("notes"),
            "label": f"{it.get('product_name')}{combo_label} x{qty} — {line_tot:.0f} EGP",
        })

    # Round final cart total to guard against floating point inaccuracies
    total = round(total, 2)
    return {
        "items": item_summaries,
        "total_price": total,
        "items_count": sum(it.get("quantity", 1) for it in items),
    }

def format_draft_summary(draft: dict[str, Any]) -> str:
    """Format full human-readable Markdown summary of the draft order."""
    calc = calculate_draft_totals(draft)
    order_type = draft.get("order_type") or "Not specified"
    type_display = {
        "delivery": "🚀 Delivery",
        "pickup": "🏬 Pickup",
        "dine_in": "🍽️ Dine-in",
    }.get(order_type, order_type)

    lines = ["### 🧾 Order Summary\n"]
    lines.append(f"* **Order Type**: {type_display}")
    if draft.get("customer_name"):
        lines.append(f"* **Customer Name**: {draft['customer_name']}")
    if draft.get("customer_phone"):
        lines.append(f"* **Phone Number**: {draft['customer_phone']}")

    if order_type == "delivery":
        lines.append(f"* **Delivery Address**: {draft.get('delivery_address') or '*(Missing)*'}")
    elif order_type == "pickup":
        lines.append(f"* **Pickup Branch**: {draft.get('pickup_branch') or '*(Missing)*'}")
    elif order_type == "dine_in":
        lines.append(f"* **Table Number**: {draft.get('table_number') or '*(Missing)*'}")

    lines.append(f"* **Payment Method**: {draft.get('payment_method') or '*(Missing)*'}")
    lines.append("\n#### 🛒 Items:")
    if not calc["items"]:
        lines.append("* *(No items added yet)*")
    else:
        for it in calc["items"]:
            combo_note = f" *(+Combo: {it['combo_price']:.0f} EGP)*" if it["is_combo"] else ""
            notes_str = f" [{it['notes']}]" if it.get("notes") else ""
            lines.append(f"* **{it['name']}** x{it['quantity']}{combo_note}{notes_str} — {it['line_total']:.0f} EGP")

    lines.append(f"\n**Total Amount**: {calc['total_price']:.0f} EGP")
    return "\n".join(lines)

def update_draft(session_id: str, **kwargs) -> dict[str, Any]:
    """Update draft fields and return the updated draft."""
    draft = get_draft(session_id)
    old_type = draft.get("order_type")
    new_type = kwargs.get("order_type")

    # If order type changed, clear fields specific to other types
    if new_type and new_type != old_type:
        draft["order_type"] = new_type
        if new_type == "delivery":
            draft["pickup_branch"] = None
            draft["table_number"] = None
        elif new_type == "pickup":
            draft["delivery_address"] = None
            draft["table_number"] = None
        elif new_type == "dine_in":
            draft["delivery_address"] = None
            draft["pickup_branch"] = None

    for key, val in kwargs.items():
        if key == "order_type":
            continue
        if val is not None:
            draft[key] = val

    _save_draft_to_db(session_id, draft)
    return draft

@_with_app_context
def add_item_to_draft(session_id: str, product_name: str, quantity: int = 1, is_combo: bool = False, notes: str = "") -> dict[str, Any]:
    """
    Add or update an item in the session draft using database product metadata.
    Avoids duplicate entries for the exact same product and combo option by combining quantities.
    If the session previously completed and confirmed an order, clear the previous draft so
    the new order starts clean without old customer data bleeding through.
    """
    draft = get_draft(session_id)
    # If a prior order was already placed in this chat, start a fresh cart so old customer data does not bleed through
    if draft.get("stage") == "confirmed" or draft.get("confirmed_order_code"):
        clear_draft(session_id)
        draft = get_draft(session_id)

    p_clean = product_name.strip()
    alias_map = {
        "بيبسي": "مشروب",
        "pepsi": "مشروب",
        "cola": "مشروب",
        "drink": "مشروب",
        "water": "مياه",
    }
    p_clean = alias_map.get(p_clean.lower(), p_clean)
    product = Product.query.filter(Product.name.ilike(p_clean)).first()
    if not product:
        product = Product.query.filter(Product.name.ilike(f"%{p_clean}%")).first()

    if not product:
        return {"ok": False, "error": f"Product '{product_name}' not found."}

    # Block ordering out-of-stock items before adding to cart
    if not product.is_available:
        return {"ok": False, "error": f"Product '{product.name}' is currently out of stock."}

    # Only charge combo fees if the product has a configured combo upgrade price
    combo_fee = product.combo_price if (is_combo and product.combo_price) else 0.0
    actual_combo = bool(is_combo and combo_fee > 0)

    # Combine quantities if the customer orders the exact same item and combo tier again
    existing_item = None
    for it in draft["items"]:
        if it["product_name"] == product.name and it.get("is_combo") == actual_combo:
            existing_item = it
            break

    if existing_item:
        existing_item["quantity"] += max(1, quantity)
        if notes:
            existing_item["notes"] = f"{existing_item.get('notes', '')}, {notes}".strip(", ")
    else:
        draft["items"].append({
            "product_id": product.id,
            "product_name": product.name,
            "quantity": max(1, quantity),
            "unit_price": product.price,
            "is_combo": actual_combo,
            "combo_price": combo_fee,
            "notes": notes or None,
        })

    _save_draft_to_db(session_id, draft)
    return {"ok": True, "draft": draft, "calc": calculate_draft_totals(draft)}

def remove_item_from_draft(session_id: str, product_name: str) -> dict[str, Any]:
    """Remove item(s) matching product_name from draft."""
    draft = get_draft(session_id)
    initial_len = len(draft["items"])
    draft["items"] = [it for it in draft["items"] if product_name.strip().lower() not in it["product_name"].lower()]
    _save_draft_to_db(session_id, draft)
    return {"ok": True, "removed": initial_len - len(draft["items"]), "draft": draft}

@_with_app_context
def get_upsell_suggestions(draft: dict[str, Any]) -> dict[str, Any]:
    """
    Detects relevant available extras from menu data:
    - Meal combo upgrades (+50 EGP for fries & drink) for any meal without combo.
    - Popular drinks (Pepsi 20 EGP, Water 10 EGP) if no drink is in draft.
    - Popular sauces (Garlic dip, BBQ, Ranch, Cheddar 15 EGP) if no sauce is in draft.
    """
    items = draft.get("items", [])
    eligible_meals_for_combo = []
    has_drink = False
    has_sauce = False

    # Inspect current basket to avoid annoying customers by recommending items they already selected
    for item in items:
        prod = db.session.get(Product, item.get("product_id")) if item.get("product_id") else None
        cat = prod.category if prod else ""
        if cat == "Meals" and not item.get("is_combo") and prod and prod.combo_price and prod.combo_price > 0:
            eligible_meals_for_combo.append(item["product_name"])
        elif cat == "Drinks" or any(w in item["product_name"].lower() for w in ["drink", "مياه", "مشروب", "بيبسي"]):
            has_drink = True
        elif cat == "Sauces" or any(w in item["product_name"].lower() for w in ["ثومية", "صوص", "sauce"]):
            has_sauce = True

    needs_upsell = bool(eligible_meals_for_combo or not has_drink or not has_sauce)

    return {
        "needs_upsell": needs_upsell,
        "eligible_meals_for_combo": eligible_meals_for_combo,
        "suggest_combo": len(eligible_meals_for_combo) > 0,
        "suggest_drink": not has_drink,
        "suggest_sauce": not has_sauce,
    }

@_with_app_context
def upgrade_draft_combos(session_id: str, product_name: Optional[str] = None) -> dict[str, Any]:
    """
    Upgrade meal items in draft to combo (+50 EGP).
    If product_name is provided, upgrade only that product.
    If product_name is None, upgrade all eligible meals in the draft that do not already have combo.
    Prevents duplicate combo upgrades on the same item.
    """
    draft = get_draft(session_id)
    upgraded_count = 0
    for item in draft.get("items", []):
        if product_name and product_name.strip().lower() not in item["product_name"].lower():
            continue
        # Only upgrade meals that do not already have combo applied
        if not item.get("is_combo"):
            product = db.session.get(Product, item.get("product_id")) if item.get("product_id") else None
            if product and product.combo_price and product.combo_price > 0:
                item["is_combo"] = True
                item["combo_price"] = product.combo_price
                upgraded_count += 1
            elif item.get("combo_price", 0) > 0:
                item["is_combo"] = True
                upgraded_count += 1
    draft["upsell_offered"] = True
    draft["stage"] = "collecting_details"
    _save_draft_to_db(session_id, draft)
    return {"ok": True, "upgraded_count": upgraded_count, "draft": draft, "calc": calculate_draft_totals(draft)}

@_with_app_context
def commit_confirmed_order(session_id: str) -> dict[str, Any]:
    """
    Validate all required fields, persist customer and order to SQLite DB,
    and return the result.
    If required information is missing, refuse confirmation.
    If already confirmed, return the existing confirmation without duplicate creation.
    """
    draft = get_draft(session_id)

    # Idempotency guard: if already committed, return the existing order rather than creating a duplicate
    if draft.get("confirmed_order_code"):
        existing_order = Order.query.filter_by(order_code=draft["confirmed_order_code"]).first()
        if existing_order:
            return {
                "ok": True,
                "already_confirmed": True,
                "order_code": existing_order.order_code,
                "order_id": existing_order.id,
                "customer_name": existing_order.customer.name if existing_order.customer else None,
                "customer_phone": existing_order.customer.phone if existing_order.customer else None,
                "order_type": existing_order.order_type,
                "payment_method": existing_order.payment_method,
                "delivery_address": existing_order.delivery_address,
                "pickup_branch": existing_order.pickup_branch,
                "table_number": existing_order.table_number,
                "status": existing_order.status,
                "total_price": existing_order.total_price,
                "items": [it.to_dict() for it in existing_order.items],
            }

    if not draft.get("items"):
        return {
            "ok": False,
            "error": "Cannot confirm an empty order. Please select at least one item first.",
            "missing_fields": ["items"],
        }

    # Ensure customers make a decision on suggested extras before placing the final order
    if draft.get("stage") == "offering_extras":
        return {
            "ok": False,
            "error": "Cannot confirm order while offering extras. Please accept or decline extras first.",
        }

    missing = get_missing_fields(draft)
    if missing:
        return {
            "ok": False,
            "error": f"Cannot confirm order. Missing required information: {', '.join(missing)}.",
            "missing_fields": missing,
        }

    # 1. Persist or find Customer record: links the order to a canonical customer profile deduplicated by normalized phone
    cust_name = draft.get("customer_name")
    if not cust_name or not cust_name.strip():
        cust_name = f"Customer {draft.get('customer_phone', '')[-4:]}" if draft.get("customer_phone") else "Valued Customer"
        draft["customer_name"] = cust_name

    customer_res = find_or_create_customer(
        name=cust_name,
        phone=draft["customer_phone"],
        address=draft["delivery_address"] if draft["order_type"] == "delivery" else "",
    )
    if not customer_res.get("ok"):
        return {"ok": False, "error": f"Customer creation failed: {customer_res.get('error')}"}

    customer_id = customer_res["id"]

    # 2. Prepare items for create_order: lock in line unit prices with combo fees included
    items_to_create = []
    for it in draft["items"]:
        items_to_create.append({
            "product_id": it.get("product_id"),
            "product_name": it["product_name"],
            "quantity": it["quantity"],
            "unit_price": it["unit_price"] + (it["combo_price"] if it.get("is_combo") else 0.0),
            "is_combo": it.get("is_combo", False),
            "notes": it.get("notes"),
        })

    # 3. Call create_order within transaction: generates unique ORD-XXXXX code and commits Order + OrderItems atomically
    order_res = create_order(
        customer_id=customer_id,
        items=items_to_create,
        order_type=draft["order_type"],
        payment_method=draft["payment_method"],
        delivery_address=draft.get("delivery_address") or "",
        pickup_branch=draft.get("pickup_branch") or "",
        table_number=draft.get("table_number") or "",
        status="In Kitchen",
    )

    if order_res.get("ok"):
        # Stamp confirmed order code and stage so session idempotency and status tracking are guaranteed
        draft["confirmed_order_code"] = order_res["order_code"]
        draft["stage"] = "confirmed"
        _save_draft_to_db(session_id, draft)

    return order_res