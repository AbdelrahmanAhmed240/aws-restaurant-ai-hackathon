# Building an Ultra-Responsive Restaurant AI Agent with Strands Decider 2B and Google Gemini

**Tags**: `#strands-decider-2b` `#tool-selection`  
**Author**: Abdelrahman Ahmed  
**Project**: Break Restaurant AI Agent  

---

## Executive Summary

Stateful conversational agents for restaurant ordering frequently fail in production due to three compounding failure modes:
1. **High Routing Latency**: Invoking general-purpose frontier LLMs for routine control-flow decisions adds 800ms–2500ms per turn.
2. **Hallucination of Transactional State**: LLMs frequently invent fake order confirmation codes, alter prices, or drop order modifications.
3. **Graph Orchestration Bloat**: Complex graph frameworks introduce opaque state machines, debug friction, and unpredictable serialization loops.

In this project, we built a production-grade restaurant ordering agent for **Break Restaurant** utilizing a decoupled hybrid AI architecture:
- **Strands Decider 2B** (`#strands-decider-2b`): A 2B small language model loaded once as an in-process CPU singleton, executing calibrated, structured **#tool-selection** in single-digit milliseconds.
- **Google Gemini**: Powering empathetic, natural-language customer dialogue via the official Google Gen AI SDK (`gemini-2.5-flash`), strictly constrained to authoritative runtime context.
- **Direct Python Orchestration**: Replacing brittle graph abstractions with traceable Python control flow, deterministic business rules, fuzzy branch disambiguation, and transactional SQLite persistence.

---

## Architecture & System Design

```
+-------------------------------------------------------------------------+
| Customer Web / Mobile Interface                                         |
+------------------------------------+------------------------------------+
                                     | HTTP POST /chat
                                     v
+------------------------------------+------------------------------------+
| Flask Gateway & Session Manager                                         |
+------------------------------------+------------------------------------+
                                     | run(session_id, message)
                                     v
+------------------------------------+------------------------------------+
| ToolSelectionDispatcher (#strands-decider-2b #tool-selection)           |
| Typed ChoiceQuestion Schema over 5 Discrete Tools                       |
+----+-------------------+-------------------+--------------------+-------+
     |                   |                   |                    |       |
     v                   v                   v                    v       v
[MENU_QUERY]  [PRICE_BUDGET_INQUIRY]  [ORDER_CART_OPS]  [ORDER_TRACKING] [KNOWLEDGE_FAQ]
(Full Menu)   (100/50 EGP Budgets)    (Drafts & Checkout)  (DB Tracking)   (RAG Chunks)
     |                   |                   |                    |       |
     +-------------------+-------------------+--------------------+-------+
                                     |
                                     v Authoritative Grounded Context
+------------------------------------+------------------------------------+
| Google Gemini (2.5 Flash Response Generation)                            |
| Generative Conversational Chat Synthesis                                 |
+------------------------------------+------------------------------------+
                                     | Clean Customer Response
                                     v
                               [Customer]
```

### The Separation of Concerns: Decision vs. Generation

A fundamental design tenet of this system is that **Decider 2B makes decisions; Google Gemini generates conversational language**:
- Decider 2B never produces freeform natural text; it emits calibrated categorical decisions using a pre-rendered `ChoiceQuestion`.
- Google Gemini is provided with authoritative, ground-truth context (itemized draft totals, verified branch listings, or order tracking records) and is strictly forbidden from calculating totals or fabricating order numbers.

---

## Reusable Decision Pattern: `#tool-selection`

The system defines a reusable typed `ToolSelectionDispatcher` and `InterventionHandler` that any developer can integrate into their conversational agents:

```python
# app/services/decision_pattern.py
# Tags: #strands-decider-2b #tool-selection

from dataclasses import dataclass
from typing import Dict, List, Literal, TypedDict
from strands_decider.schema import ChoiceQuestion

ToolActionName = Literal[
    "MENU_QUERY",
    "PRICE_BUDGET_INQUIRY",
    "ORDER_CART_OPS",
    "ORDER_TRACKING",
    "KNOWLEDGE_FAQ",
]

class ToolDecision(TypedDict):
    tool: ToolActionName
    route: str  # "TOOLS" or "RAG"
    confidence: float
    probabilities: Dict[str, float]
    is_fallback: bool
    tags: List[str]

class ToolSelectionDispatcher:
    def get_choice_question(self) -> ChoiceQuestion:
        return ChoiceQuestion(
            instructions=(
                "Select the exact restaurant tool action required to handle this customer message "
                "given the active conversation state. Tags: #tool-selection #strands-decider-2b"
            ),
            criteria={
                "MENU_QUERY": "Customer wants to view or explore the full restaurant menu.",
                "PRICE_BUDGET_INQUIRY": "Customer inquires about prices, cheapest meals, or budget constraints (e.g., under 100 EGP).",
                "ORDER_CART_OPS": "Customer wants to order food, add dishes, accept combo upgrades, provide fulfillment details, or confirm.",
                "ORDER_TRACKING": "Customer wants to track or check status of an existing order code (e.g., ORD-12345).",
                "KNOWLEDGE_FAQ": "Customer asks general questions about branch addresses, operating hours, delivery policies, or contact details.",
            },
        )
```

### Dynamic Intervention Handling

When a customer interrupts an ongoing order draft to ask an out-of-flow policy question (e.g. *"What is your cancellation policy?"* or *"What branches can I pick up from?"*), the `InterventionHandler` identifies the query as `KNOWLEDGE_FAQ`, retrieves verified knowledge chunks from ChromaDB/Markdown, injects the answers into the turn, and **preserves the customer's draft and cart items untouched**.

---

## Deterministic Business Logic & Dynamic Entity Resolution

While Decider 2B guides high-level intent and tool dispatching, all arithmetic, database transactions, and entity normalization remain in deterministic Python code:

1. **Smouha Branch Disambiguation Without Guessing**:
   - The restaurant operates two distinct branches in Smouha: *Smouha Branch 1* (Cooperatives, Hatem Mosque St.) and *Smouha Branch 2* (Commercial Market).
   - When a customer says *"pick up from smouha"*, the system does not randomly pick one. It presents both options and safely waits for clarification (*"the first one"* or *"branch 2"*).
2. **Budget Recommendations**:
   - Under 100 EGP Meal Budget: The system accurately identifies that the lowest meal price is 105 EGP (Basmatio Rice Meal) and clearly reports that no meal fits under 100 EGP, while recommending add-on alternatives.
   - Under 50 EGP All-Item Budget: The system dynamically filters all qualifying individual items (Basmati Rice 35 EGP, French Fries 30 EGP, Soft Drinks 20 EGP) without including out-of-budget meals.
3. **Strict Order Idempotency**:
   - Customer confirmation requires all mandatory fields (Name, Phone, Address/Branch, Payment Method).
   - If a customer sends repeated *"confirm"* messages, the system returns the existing `ORD-XXXXX` code without generating duplicate orders in the database.

---

## Google Gemini Integration

Generative conversational chat is powered by the official Google Gen AI SDK (`google-genai`):

```python
# app/services/agent.py
from google import genai
from google.genai import types

client = genai.Client(api_key=config.GEMINI_API_KEY)

response = client.models.generate_content(
    model=config.GEMINI_MODEL,  # gemini-2.5-flash
    contents=contents,
    config=types.GenerateContentConfig(
        system_instruction=system_prompt_with_runtime_context,
        temperature=0.3,
        max_output_tokens=2048,
    ),
)
customer_facing_text = response.text
```

---

## Empirical Verification: Latency & Reliability Comparison

| Metric / Characteristic | Legacy Graph Architecture | Strands Decider 2B + Gemini + Python Control Flow |
| :--- | :--- | :--- |
| **Routing Mechanism** | Multi-node Graph / Regex rules | **Strands Decider 2B ChoiceQuestion SLM** |
| **Tool Selection** | Hardcoded heuristics | **Dynamic #tool-selection with calibrated probabilities** |
| **Routing Latency** | 450ms – 1200ms | **15ms – 45ms (In-Process CPU Singleton)** |
| **Confirmation Integrity** | Risk of dropped items / total recalculation | **100% Authoritative Draft & DB Transactional Commit** |
| **PII Observability** | Raw prompts logged | **Structured `[TIMING]` metrics (Zero-PII)** |
| **Test Suite Pass Rate** | Intermittent flakiness | **59 / 59 Automated Tests Passing (100%)** |

### Structured Timing Observability
Every turn produces structured telemetry without exposing customer names, phone numbers, or tokens:
```
[TIMING] session_prefix=a1b2c3d4 intent=TOOLS is_fallback=False route_ms=18.4 handler=order_tool_node handler_ms=12.1 llm_ms=210.3 bypassed_llm=False total_ms=240.8
```

---

## Conclusion

Pairing **Strands Decider 2B** for discrete, low-latency decision-making with **Google Gemini** for rich generative language creates a scalable, cost-effective blueprint for real-world conversational systems. By grounding all transactional actions in deterministic Python and SQLite, businesses can completely eliminate hallucinated orders while delivering sub-second response times.

*For complete implementation code, schemas, and tests, visit the project repository: [aws-restaurant-ai-hackathon](https://github.com/AbdelrahmanAhmed240/aws-restaurant-ai-hackathon).*
