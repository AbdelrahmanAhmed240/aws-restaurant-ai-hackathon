"""
Dynamic Entity Recognition and Resolution Service.
Provides robust, context-aware intent and entity understanding without rigid hardcoded rules:
- Dynamic branch matching with typo tolerance (fuzzy matching via difflib), ordinal normalization,
  and explicit ambiguity detection (e.g. asking for clarification between Smouha 1 & 2 without guessing).
- Fulfillment type resolution (delivery, pickup, dine_in) with negation handling.
- Payment method resolution (Cash, Visa) with negation handling.
- Egyptian phone number validation.
- Context-aware customer name and address extraction.
"""

import re
import difflib
from typing import Any, Optional

CANONICAL_BRANCHES = [
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

# Branch metadata describing distinctive location keywords and landmarks
BRANCH_METADATA = {
    "Mohandessin Branch": {
        "city": "cairo",
        "primary_tokens": ["mohandessin", "mohandseen", "mohandseen", "مهندسين", "المهندسين"],
        "landmark_tokens": ["batal", "gameat", "dowal", "giza", "جيزة", "البطل", "جامعة الدول"],
    },
    "Mokattam Branch": {
        "city": "cairo",
        "primary_tokens": ["mokattam", "mokatam", "moqattam", "مقطم", "المقطم"],
        "landmark_tokens": ["street 9", "fountain", "monginis", "شارع 9", "النافورة"],
    },
    "Sheraton Branch": {
        "city": "cairo",
        "primary_tokens": ["sheraton", "shiraton", "شيراتون"],
        "landmark_tokens": ["heliopolis", "ankara", "zakariya", "مصر الجديدة", "انقرة"],
    },
    "Glim Branch": {
        "city": "alexandria",
        "primary_tokens": ["glim", "gleem", "جليم", "radio", "radio street", "ezaa", "san stefano", "اذاعة", "الإذاعة"],
        "landmark_tokens": ["radio", "ezaa", "san stefano", "اذاعة", "الإذاعة", "سان ستيفانو"],
    },
    "Mandara Branch": {
        "city": "alexandria",
        "primary_tokens": ["mandara", "mandarah", "مندرة", "المندرة"],
        "landmark_tokens": ["abdel halim", "santos", "عبد الحليم"],
    },
    "Camp Caesar Branch": {
        "city": "alexandria",
        "primary_tokens": ["camp", "caesar", "cesar", "كامب", "شيزار", "شزار"],
        "landmark_tokens": ["wali", "beachfront", "والي"],
    },
    "Smouha Branch 1": {
        "city": "alexandria",
        "primary_tokens": ["smouha", "semouha", "سموحة"],
        "ordinal": 1,
        "landmark_tokens": ["cooperatives", "security", "hatem", "victor", "emmanuel", "الامن", "الأمن", "تعاونيات", "حاتم", "فيكتور"],
    },
    "Smouha Branch 2": {
        "city": "alexandria",
        "primary_tokens": ["smouha", "semouha", "سموحة"],
        "ordinal": 2,
        "landmark_tokens": ["commercial", "market", "club", "fawzi", "moaz", "تجاري", "السوق", "نادي", "فوزي", "معاذ"],
    },
    "Bahary Branch": {
        "city": "alexandria",
        "primary_tokens": ["bahary", "bahari", "بحري"],
        "landmark_tokens": ["citadel", "qaitbay", "saidi", "قلعة", "قايتباي", "الصعيدي"],
    },
    "Sidi Bishr Branch": {
        "city": "alexandria",
        "primary_tokens": ["sidi bishr", "sidi beshr", "bishr", "بشر", "سيدي بشر"],
        "landmark_tokens": ["eisawy", "electricity", "العيساوي", "الكهرباء"],
    },
    "Mahrousa Branch": {
        "city": "alexandria",
        "primary_tokens": ["mahrousa", "mahrouseh", "محروسة", "المحروسة"],
        "landmark_tokens": ["tunnel", "corniche", "نفق", "الكورنيش"],
    },
}

def normalize_text(text: str) -> str:
    """Normalize English and Arabic text for robust comparison."""
    if not text:
        return ""
    t = text.lower().strip()
    # Normalize Arabic diacritics and letter variants
    t = re.sub(r"[\u064B-\u065F\u0670]", "", t)  # Tashkeel
    t = re.sub(r"[إأآا]", "ا", t)
    t = re.sub(r"ة", "ه", t)
    t = re.sub(r"ى", "ي", t)
    # Normalize punctuation to spaces
    t = re.sub(r"[^\w\s\d]", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def _fuzzy_token_match(token: str, target: str, threshold: float = 0.75) -> bool:
    """Check if token is equal or fuzzy-similar to target."""
    if token == target:
        return True
    if len(token) >= 4 and len(target) >= 4:
        ratio = difflib.SequenceMatcher(None, token, target).ratio()
        if ratio >= threshold:
            return True
    return False

def _extract_ordinal(text: str) -> Optional[int]:
    """Detect ordinal number indicators (1st, 2nd, first, second, 1, 2, الأول, الثاني, etc.)."""
    t = normalize_text(text)
    # Check 1 indicators
    one_tokens = {
        "1", "one", "first", "1st", "واحد", "الاول", "الأول", "اول", "أول", "الاولى", "الأولى",
        "victor", "فيكتور", "cooperatives", "تعاونيات", "security", "الامن",
    }
    # Check 2 indicators
    two_tokens = {
        "2", "two", "second", "2nd", "اتنين", "اثنين", "تاني", "التاني", "الثاني", "ثاني", "التانيه",
        "fawzi", "فوزي", "market", "تجاري", "club", "نادي",
    }

    words = set(t.split())
    if words & one_tokens:
        return 1
    if words & two_tokens:
        return 2

    # Check regex for phrases like "branch 1" or "فرع 1"
    if re.search(r"\b(?:branch|barnch|brnch|فرع)\s*1\b", t) or re.search(r"\b1\b", t):
        return 1
    if re.search(r"\b(?:branch|barnch|brnch|فرع)\s*2\b", t) or re.search(r"\b2\b", t):
        return 2

    return None

def resolve_branch(text: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """
    Dynamically resolve branch name from user input with typo tolerance and ambiguity detection.
    
    Returns dict:
      - matched: Canonical branch name (str) or None
      - confidence: float (0.0 to 1.0)
      - is_ambiguous: bool (True if clarification needed between candidates)
      - candidates: list of candidate branch names
      - clarification_prompt: Formatted text to present to customer if ambiguous
    """
    clean = normalize_text(text)
    if not clean:
        return {"matched": None, "confidence": 0.0, "is_ambiguous": False, "candidates": []}

    words = clean.split()

    # Context check: if the active draft was waiting for Smouha branch clarification
    if context and context.get("awaiting_branch_clarification") == "smouha":
        ord_val = _extract_ordinal(clean)
        if ord_val == 1:
            return {"matched": "Smouha Branch 1", "confidence": 1.0, "is_ambiguous": False, "candidates": []}
        elif ord_val == 2:
            return {"matched": "Smouha Branch 2", "confidence": 1.0, "is_ambiguous": False, "candidates": []}

    # Informational question guard: if text is a general inquiry about what branches exist
    inquiry_markers = ("what", "which", "where", "how", "list", "show", "can i", "do you", "أين", "فين", "ما هي", "ايه هي", "إيه هي", "كام")
    is_inquiry = any(q in clean for q in inquiry_markers) and any(b in clean for b in ("branch", "branches", "pickup", "فرع", "فروع", "استلام")) and ("?" in text or "؟" in text)
    if is_inquiry:
        return {"matched": None, "confidence": 0.0, "is_ambiguous": False, "candidates": []}

    # Score each canonical branch against input words
    scores: dict[str, float] = {}
    is_smouha_mentioned = False

    for b_name, meta in BRANCH_METADATA.items():
        score = 0.0
        # Check primary area tokens (e.g. "mohandessin", "smouha", "glim")
        for p_tok in meta["primary_tokens"]:
            norm_p = normalize_text(p_tok)
            if any(_fuzzy_token_match(w, norm_p) for w in words):
                score += 0.60
                if "smouha" in norm_p:
                    is_smouha_mentioned = True
                break
            elif norm_p in clean:
                score += 0.60
                if "smouha" in norm_p:
                    is_smouha_mentioned = True
                break

        # Check landmark/street tokens (e.g. "radio", "fawzi moaz", "batal")
        for l_tok in meta["landmark_tokens"]:
            norm_l = normalize_text(l_tok)
            if any(_fuzzy_token_match(w, norm_l) for w in words):
                score += 0.35
                break
            elif norm_l in clean:
                score += 0.35
                break

        # Check branch word typo (e.g. "barnch", "brnch", "فرع")
        has_branch_word = any(_fuzzy_token_match(w, "branch", 0.70) or _fuzzy_token_match(w, "فرع", 0.80) for w in words)
        if has_branch_word and score > 0:
            score += 0.10

        # Check ordinal matching for numbered branches (Smouha 1 vs Smouha 2)
        if "ordinal" in meta:
            ord_detected = _extract_ordinal(clean)
            if ord_detected is not None:
                if ord_detected == meta["ordinal"]:
                    score += 0.40
                else:
                    # Penalize mismatching ordinal
                    score -= 0.50

        scores[b_name] = max(0.0, score)

    # Check for Smouha ambiguity
    if is_smouha_mentioned:
        ord_detected = _extract_ordinal(clean)
        if ord_detected == 1:
            return {"matched": "Smouha Branch 1", "confidence": 0.95, "is_ambiguous": False, "candidates": []}
        elif ord_detected == 2:
            return {"matched": "Smouha Branch 2", "confidence": 0.95, "is_ambiguous": False, "candidates": []}
        else:
            # Customer said "smouha" without specifying 1 or 2.
            # Do NOT guess! Mark as ambiguous and ask for clarification.
            return {
                "matched": None,
                "confidence": 0.50,
                "is_ambiguous": True,
                "ambiguity_type": "smouha",
                "candidates": ["Smouha Branch 1", "Smouha Branch 2"],
                "clarification_prompt": (
                    "We have two branches in Smouha:\n"
                    "1. **Smouha Branch 1** (Victor Emmanuel Square / Hatem Mosque St)\n"
                    "2. **Smouha Branch 2** (Commercial Market, Hatem Mosque St)\n\n"
                    "Which one would you like to pick up from?"
                ),
            }

    # Sort remaining branches by score
    sorted_branches = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_branch, best_score = sorted_branches[0]

    # Acceptance threshold
    if best_score >= 0.55:
        # Check margin over second best to prevent false positives
        second_score = sorted_branches[1][1] if len(sorted_branches) > 1 else 0.0
        if best_score - second_score >= 0.15 or best_score >= 0.70:
            return {
                "matched": best_branch,
                "confidence": min(1.0, best_score),
                "is_ambiguous": False,
                "candidates": [best_branch],
            }

    return {"matched": None, "confidence": 0.0, "is_ambiguous": False, "candidates": []}

def resolve_fulfillment_type(text: str) -> Optional[str]:
    """
    Detect fulfillment channel (delivery, pickup, dine_in) handling negation and phrasing variants.
    """
    if not text:
        return None

    t = text.lower().strip()

    # Ignore question comparisons like "do you have delivery or pickup?"
    if ("?" in text or "؟" in text) and any(w in t for w in ("or", "ولا", "ام", "أم")):
        return None

    def _is_negated(pattern: str, raw_text: str) -> bool:
        match = re.search(pattern, raw_text, re.IGNORECASE)
        if not match:
            return False
        start = match.start()
        # Split by clause boundaries (punctuation, contrastive conjunctions)
        clause = re.split(r"[,.;!?]|\b(?:but|instead|please|بس|لكن|بدل|لو سمحت)\b", raw_text[:start], flags=re.IGNORECASE)[-1].strip()
        return bool(re.search(r"\b(?:no|not|don'?t|never|without|مش|لا|بلاش|بدون)\b(?:\s+\w+)?\s*$", clause, re.IGNORECASE))

    # Delivery signals
    delivery_pat = r"\b(?:delivery|deliver|delievery|home\s+delivery|توصيل|دليفري|للمنزل|علي\s*البيت|على\s*البيت)\b"
    # Pickup signals
    pickup_pat = r"\b(?:pickup|pick\s*up|takeaway|take\s*away|collect|grab|استلام|من\s*الفرع|تيك\s*اواي|سفري|هاجي\s*اخده)\b"
    # Dine-in signals
    dine_pat = r"\b(?:dine\s*in|dinein|eat\s*in|table|at\s*the\s*restaurant|صاله|صالة|في\s*المطعم|ترابيزه|ترابيزة|طاوله|طاولة)\b"

    has_delivery = bool(re.search(delivery_pat, t))
    has_pickup = bool(re.search(pickup_pat, t))
    has_dine = bool(re.search(dine_pat, t))

    del_negated = _is_negated(delivery_pat, text) if has_delivery else False
    pick_negated = _is_negated(pickup_pat, text) if has_pickup else False
    dine_negated = _is_negated(dine_pat, text) if has_dine else False

    if has_delivery and not del_negated:
        return "delivery"
    if has_pickup and not pick_negated:
        return "pickup"
    if has_dine and not dine_negated:
        return "dine_in"

    return None

def resolve_payment_method(text: str) -> Optional[str]:
    """
    Detect payment method (Cash, Visa) handling negation and phrasing variants.
    """
    if not text:
        return None

    t = text.lower().strip()

    cash_pat = r"\b(?:cash|cod|pay\s+on\s+delivery|cash\s+on\s+delivery|كاش|نقد|نقدي|عند\s*الاستلام)\b"
    visa_pat = r"\b(?:visa|card|credit|debit|mastercard|online\s+payment|فيزا|كارت|بطاقه|بطاقة|دفع\s*الكتروني)\b"

    def _is_negated(pat: str) -> bool:
        m = re.search(pat, t, re.IGNORECASE)
        if not m:
            return False
        clause = re.split(r"[,.;!?]|\b(?:but|instead|please|بس|لكن|بدل|لو سمحت)\b", text[:m.start()], flags=re.IGNORECASE)[-1].strip()
        return bool(re.search(r"\b(?:no|not|don'?t|never|without|مش|لا|بلاش|بدون)\b(?:\s+\w+)?\s*$", clause, re.IGNORECASE))

    has_cash = bool(re.search(cash_pat, t))
    has_visa = bool(re.search(visa_pat, t))

    cash_neg = _is_negated(cash_pat) if has_cash else False
    visa_neg = _is_negated(visa_pat) if has_visa else False

    if has_cash and not cash_neg:
        return "Cash"
    if has_visa and not visa_neg:
        return "Visa"

    return None

def validate_and_extract_phone(text: str) -> tuple[Optional[str], bool]:
    """
    Extract and validate Egyptian mobile phone numbers (11 digits, prefixes 010, 011, 012, 015).
    Returns (phone_str, is_invalid_attempt).
    """
    # Canonical Egyptian mobile format
    match = re.search(r"(?:(?:\+?20)|0)?(1[0125]\d{8})\b", text)
    if match:
        return f"0{match.group(1)}", False

    # Check if user attempted to provide a phone number with invalid format
    cleaned_digits = re.sub(r"[^\d]", "", text)
    if 5 <= len(cleaned_digits) <= 15:
        # User entered a digit sequence that failed valid Egyptian mobile criteria
        if not text.strip().startswith("#"):
            return None, True

    return None, False