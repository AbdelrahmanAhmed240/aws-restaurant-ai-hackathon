# Restaurant AI Agent

## What It Does

This project is a restaurant-facing AI agent built with Flask.
It answers customer questions, recommends products, and performs real order operations using a relational database.
Administrators can manage menu items, orders, customers, and the RAG knowledge base from a dashboard.

## Main Features

- Customer service conversations
- Product and menu questions
- AI recommendations based on real product data
- RAG knowledge base with Markdown sources
- Order creation and tracking
- Conversation context during a session
- Admin dashboard

## Architecture

Customer
→ Flask
→ LangGraph
→ RAG / Tools
→ SQLAlchemy + SQLite
→ Response

## RAG

- Knowledge is stored in Markdown files and `KnowledgeItem` records.
- Documents are split into semantic chunks.
- Embeddings are generated and stored in ChromaDB.
- Retrieval is used when answering restaurant and product questions.
- Admin can add, edit, and delete knowledge from the dashboard.
- Changes are reindexed and immediately available to the agent.

## LangGraph

The agent uses a simplified 2-path LangGraph workflow:

- **Router**: Classifies intent into information or ordering
- **RAG (`rag_node`)**: Retrieves relevant menu and policy context from ChromaDB
- **Order Tools (`order_tool_node`)**: Manages draft items, fulfillment details, and atomic database commits
- **LLM (`llm_node`)**: Generates grounded, contextual responses using Gemini

This keeps the flow explicit and prevents the model from acting without the right context.

## Business Actions

The agent can perform real database actions:

- Create order
- Track order

Once placed, orders are final and cannot be modified or cancelled by customers.

It uses the existing SQLAlchemy models and validation rules.
The database is the source of truth.

## Admin Dashboard

Admin pages manage:

- Products
- Orders
- Customers
- Knowledge/RAG data

## Project Structure

```
app/
  models/
  routes/
  services/
  templates/
knowledge/
config.py
run.py
requirements.txt
README.md
```

## Setup & Quickstart

1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Configure Environment:**
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   Add your Google Gemini API key:
   ```env
   LLM_PROVIDER=gemini
   GEMINI_API_KEY=your_gemini_api_key_here
   GEMINI_MODEL=gemini-2.5-flash
   GEMINI_EMBEDDING_MODEL=gemini-embedding-001
   ```
   *(Get your key from [Google AI Studio](https://aistudio.google.com/)).*

3. **Rebuild ChromaDB Vectors with Gemini Embeddings:**
   Once your `GEMINI_API_KEY` is added, rebuild your knowledge vector index:
   - Either navigate to the Admin Dashboard at `http://127.0.0.1:5000/admin/knowledge` and click **"Rebuild Vectors"**,
   - Or run in Python:
     ```bash
     python -c "from app import create_app; from app.services.knowledge_sync import rebuild_vector_index; app = create_app(); app.app_context().push(); print('Indexed chunks:', rebuild_vector_index())"
     ```

4. **Start the Application:**
   ```bash
   python run.py
   ```
   Open `http://127.0.0.1:5000` or admin dashboard at `http://127.0.0.1:5000/admin`.

## Environment Variables

| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | Google Gemini API key | *(required for live Gemini)* |
| `GEMINI_MODEL` | Selected Gemini generation model | `gemini-2.5-flash` |
| `GEMINI_EMBEDDING_MODEL` | Official Gemini embedding model | `gemini-embedding-001` |
| `DATABASE_URI` | SQLite database URI | `sqlite:///restaurant.db` |
| `CHROMA_PERSIST_DIR` | Chroma vector database directory | `./data/chroma_db` |
| `AGENT_TEMPERATURE` | Model generation temperature | `0.3` |
| `AGENT_MAX_TOKENS` | Max response tokens | `512` |

Never commit real secret values.

## Model Selection & Discovery

To change the active Gemini model, edit `GEMINI_MODEL` in your `.env` file without changing Python code:
- `gemini-2.5-flash` (Recommended default: fast, highly capable, supports structured tool use)
- `gemini-2.5-pro` (High-reasoning model for complex queries)
- `gemini-2.0-flash` (Alternative fast flash model)

For embeddings, `GEMINI_EMBEDDING_MODEL` defaults to `gemini-embedding-001`, Google's official stable embedding model.

## Troubleshooting Common API Errors

- **`Gemini API key is not configured`**: Add `GEMINI_API_KEY=your_key` to `.env`.
- **`Invalid Gemini API key`**: Verify key validity on [Google AI Studio](https://aistudio.google.com/).
- **`Configured Gemini model 'xyz' was not found`**: Verify model spelling in `GEMINI_MODEL`.
- **`Sorry, the Gemini AI service is currently rate-limited`**: Wait a brief moment or upgrade quota tier.
- **`Dimensional mismatch in ChromaDB`**: If switching embedding models, click **"Rebuild Vectors"** in the Admin Dashboard (`/admin/knowledge`) to recreate the collection with the new vector dimensions.
