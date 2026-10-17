from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app.models import db, Product, Customer, Order, KnowledgeItem, ChatSession, ChatMessage
from app.services.agent import get_history as agent_get_history
from app.services.decider import run as decider_run

admin_bp = Blueprint("admin", __name__)

# Main Dashboard Overview
@admin_bp.route("/")
@admin_bp.route("/dashboard")
def dashboard():
    """Renders main dashboard overview with summary metrics and recent orders."""
    total_products = Product.query.count()
    total_customers = Customer.query.count()
    total_orders = Order.query.count()
    total_knowledge = KnowledgeItem.query.count()

    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(5).all()

    return render_template(
        "dashboard.html",
        total_products=total_products,
        total_customers=total_customers,
        total_orders=total_orders,
        total_knowledge=total_knowledge,
        recent_orders=recent_orders,
    )

# Products Management View
@admin_bp.route("/products")
def products():
    """Lists all menu products with category filter and search."""
    category = request.args.get("category", "")
    query = request.args.get("q", "").strip()

    products_query = Product.query

    if category:
        products_query = products_query.filter_by(category=category)
    if query:
        products_query = products_query.filter(Product.name.ilike(f"%{query}%"))

    all_products = products_query.all()
    categories = [c[0] for c in db.session.query(Product.category).distinct()]

    return render_template(
        "products.html",
        products=all_products,
        categories=categories,
        selected_category=category,
        search_query=query,
    )

@admin_bp.route("/products/new", methods=["GET", "POST"])
def new_product():
    """Create a new product."""
    if request.method == "POST":
        try:
            name = (request.form.get("name") or "").strip()
            category = (request.form.get("category") or "").strip()
            description = (request.form.get("description") or "").strip()
            price = request.form.get("price", "").strip()
            combo_price = request.form.get("combo_price", "0").strip()
            is_available = request.form.get("is_available", "True") == "True"

            if not name or not category or not price:
                flash("Name, category, and base price are required.", "error")
                return redirect(url_for("admin.new_product"))

            price_val = float(price)
            combo_val = float(combo_price) if combo_price else 0.0

            product = Product(
                name=name,
                category=category,
                description=description or None,
                price=price_val,
                combo_price=combo_val,
                is_available=is_available,
            )
            db.session.add(product)
            db.session.commit()
            flash(f"Product '{product.name}' added successfully.", "success")
            return redirect(url_for("admin.products"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to add product: {exc}", "error")
            return redirect(url_for("admin.new_product"))

    return render_template(
        "products_form.html",
        product=None,
        categories=["Meals", "Sandwiches", "Combos", "Add-ons", "Drinks", "Sides"],
    )

@admin_bp.route("/products/edit/<int:product_id>", methods=["GET", "POST"])
def edit_product(product_id):
    """Edit an existing product."""
    product = Product.query.get_or_404(product_id)

    if request.method == "POST":
        try:
            name = (request.form.get("name") or "").strip()
            category = (request.form.get("category") or "").strip()
            description = (request.form.get("description") or "").strip()
            price = request.form.get("price", "").strip()
            combo_price = request.form.get("combo_price", "0").strip()
            is_available = request.form.get("is_available", "True") == "True"

            if not name or not category or not price:
                flash("Name, category, and base price are required.", "error")
                return redirect(url_for("admin.edit_product", product_id=product_id))

            price_val = float(price)
            combo_val = float(combo_price) if combo_price else 0.0

            product.name = name
            product.category = category
            product.description = description or None
            product.price = price_val
            product.combo_price = combo_val
            product.is_available = is_available
            db.session.commit()
            flash(f"Product '{product.name}' updated successfully.", "success")
            return redirect(url_for("admin.products"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to update product: {exc}", "error")
            return redirect(url_for("admin.edit_product", product_id=product_id))

    return render_template(
        "products_form.html",
        product=product,
    )

@admin_bp.route("/products/delete/<int:product_id>", methods=["POST"])
def delete_product(product_id):
    """Delete a product permanently."""
    product = Product.query.get_or_404(product_id)
    try:
        name = product.name
        db.session.delete(product)
        db.session.commit()
        flash(f"Product '{name}' deleted permanently.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Failed to delete product: {exc}", "error")
    return redirect(url_for("admin.products"))

@admin_bp.route("/products/toggle/<int:product_id>", methods=["POST"])
def toggle_product_availability(product_id):
    """Toggles product in-stock / out-of-stock availability."""
    product = Product.query.get_or_404(product_id)
    product.is_available = not product.is_available
    db.session.commit()
    status_str = "Available" if product.is_available else "Out of Stock"
    flash(f"Product '{product.name}' is now marked as {status_str}.", "success")
    return redirect(url_for("admin.products"))

# Orders Management View (Delivery / Pickup / Dine-in)
@admin_bp.route("/orders")
def orders():
    """Lists all customer orders with filter for order type and status."""
    raw_type = request.args.get("type", "").strip()
    status = request.args.get("status", "").strip()

    orders_query = Order.query.order_by(Order.created_at.desc())

    if raw_type:
        # Normalize: 'Delivery' -> 'delivery', 'Pickup' -> 'pickup', 'Dine-in'/'dine_in' -> 'dine_in'
        t_lower = raw_type.lower().replace("-", "_")
        orders_query = orders_query.filter(
            db.or_(
                Order.order_type == raw_type,
                Order.order_type == t_lower,
                Order.order_type.ilike(t_lower)
            )
        )
    if status:
        orders_query = orders_query.filter(Order.status.ilike(status))

    all_orders = orders_query.all()

    return render_template(
        "orders.html",
        orders=all_orders,
        selected_type=raw_type,
        selected_status=status,
    )

@admin_bp.route("/orders/status/<int:order_id>", methods=["POST"])
def update_order_status(order_id):
    """Update order status (In Kitchen, Ready, Delivered, Cancelled)."""
    order = db.get_or_404(Order, order_id)
    new_status = request.form.get("status", "").strip()
    valid_statuses = ["In Kitchen", "Ready", "Delivered", "Cancelled"]
    if new_status in valid_statuses:
        order.status = new_status
        db.session.commit()
        flash(f"Order {order.order_code} status updated to {new_status}.", "success")
    else:
        flash(f"Invalid status '{new_status}'. Allowed statuses: {', '.join(valid_statuses)}.", "error")
    return redirect(url_for("admin.orders"))

@admin_bp.route("/orders/delete/<int:order_id>", methods=["POST"])
def delete_order(order_id):
    """
    Safely delete an order permanently after explicit administrator confirmation.
    Preserves referential integrity and does not delete related customer records.
    """
    order = db.get_or_404(Order, order_id)
    code = order.order_code
    try:
        db.session.delete(order)
        db.session.commit()
        flash(f"Order {code} has been deleted permanently.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Failed to delete order {code}: {exc}", "error")
    return redirect(url_for("admin.orders"))

# Customers View
@admin_bp.route("/customers")
def customers():
    """Lists all customers and their order histories."""
    all_customers = Customer.query.order_by(Customer.created_at.desc()).all()
    return render_template("customers.html", customers=all_customers)

@admin_bp.route("/customers/delete/<int:customer_id>", methods=["POST"])
def delete_customer(customer_id):
    """
    Safely delete a customer after explicit administrator confirmation.
    PRESERVES HISTORICAL ORDERS: Any historical orders belonging to this customer
    have their customer_id detached (set to NULL) while customer_name, customer_phone,
    address, order totals, items, and status remain safely preserved on the orders.
    """
    customer = db.get_or_404(Customer, customer_id)
    cust_name = customer.name or customer.phone
    try:
        # Preserve historical orders before deleting the customer record
        for ord_record in customer.orders:
            ord_record.customer_id = None
            if not ord_record.customer_name:
                ord_record.customer_name = customer.name
            if not ord_record.customer_phone:
                ord_record.customer_phone = customer.phone

        db.session.delete(customer)
        db.session.commit()
        flash(f"Customer '{cust_name}' has been deleted. Historical orders were safely preserved.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Failed to delete customer '{cust_name}': {exc}", "error")
    return redirect(url_for("admin.customers"))

# RAG Knowledge Management
from app.models import KnowledgeItem
from app.services.knowledge_sync import create_markdown_source_from_admin, delete_item_from_dashboard, sync_all, _KNOWLEDGE_DIR, _write_markdown, _reindex_markdown

# Displays RAG knowledge chunks and provides filtering/search for the knowledge dashboard.
@admin_bp.route("/knowledge")
def knowledge():
    # Auto-sync Markdown files so the UI always reflects the current filesystem state.
    try:
        sync_all()
    except Exception:
        pass

    search_query = request.args.get("q", "").strip()
    chunk_type = request.args.get("type", "")
    category = request.args.get("category", "")

    collection = __import__("app.services.vector_store", fromlist=["get_collection"]).get_collection()
    raw = collection.get(include=["documents", "metadatas"])
    chunks = []
    for idx, chunk_id in enumerate(raw.get("ids", [])):
        meta = (raw.get("metadatas", []) or [{}])[idx] if idx < len(raw.get("metadatas", []) or [{}]) else {}
        doc = (raw.get("documents", [""]) or [""])[idx] if idx < len(raw.get("documents", [""]) or [""]) else ""
        chunks.append(
            {
                "id": chunk_id,
                "source": meta.get("source", ""),
                "type": meta.get("type", ""),
                "name": meta.get("name", ""),
                "category": meta.get("category", ""),
                "content": doc,
                "vector_status": "Synced",
            }
        )

    if chunk_type:
        chunks = [c for c in chunks if c["type"] == chunk_type]
    if category:
        chunks = [c for c in chunks if c["category"] == category]
    if search_query:
        q = search_query.lower()
        chunks = [c for c in chunks if q in c["id"].lower() or q in c["name"].lower()]

    types = sorted({c["type"] for c in chunks if c["type"]})
    categories = sorted({c["category"] for c in chunks if c["category"]})

    knowledge_items_by_source = {}
    for item in KnowledgeItem.query.filter(KnowledgeItem.source_path != None).all():
        knowledge_items_by_source[item.source_path] = item.id

    knowledge_sources = sorted(knowledge_items_by_source.keys())

    return render_template(
        "knowledge.html",
        chunks=chunks,
        types=types,
        categories=categories,
        selected_type=chunk_type,
        selected_category=category,
        search_query=search_query,
        knowledge_items_by_source=knowledge_items_by_source,
        knowledge_sources=knowledge_sources,
    )

# Edits an existing Markdown knowledge source and reindexes it for RAG.
@admin_bp.route("/knowledge/source/<path:source>/edit", methods=["GET", "POST"])
def knowledge_source_edit(source: str):
    path = _KNOWLEDGE_DIR / source
    if not path.exists():
        flash("Markdown source not found.", "error")
        return redirect(url_for("admin.knowledge"))

    if request.method == "POST":
        content = request.form.get("content", "")
        if not content.strip():
            flash("Markdown content cannot be empty.", "error")
            return redirect(url_for("admin.knowledge_source_edit", source=source))

        try:
            _write_markdown(path, content)
            item = KnowledgeItem.query.filter_by(source_path=source).first()
            if item:
                item.content = content
                db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Markdown update failed.", "error")
            return redirect(url_for("admin.knowledge_source_edit", source=source))

        try:
            _reindex_markdown(path)
            flash("Markdown source updated and reindexed.", "success")
        except Exception:
            db.session.rollback()
            flash("Markdown file updated, but reindexing failed. You can retry later.", "error")

        return redirect(url_for("admin.knowledge"))

    content = path.read_text(encoding="utf-8")
    return render_template("knowledge_source_edit.html", source=source, content=content)

# Displays the details of a specific RAG vector chunk.
@admin_bp.route("/knowledge/chunks/<path:chunk_id>")
def knowledge_chunk_detail(chunk_id: str):
    collection = __import__("app.services.vector_store", fromlist=["get_collection"]).get_collection()
    raw = collection.get(ids=[chunk_id], include=["documents", "metadatas"])
    ids = raw.get("ids", [])
    metadatas = raw.get("metadatas", [])
    documents = raw.get("documents", [])
    chunk = None
    if ids:
        chunk = {
            "id": ids[0],
            "source": (metadatas[0] or {}).get("source", ""),
            "type": (metadatas[0] or {}).get("type", ""),
            "name": (metadatas[0] or {}).get("name", ""),
            "category": (metadatas[0] or {}).get("category", ""),
            "content": documents[0] if documents else "",
            "vector_status": "Synced",
        }

    return render_template("knowledge_chunk_detail.html", chunk=chunk)

# Creates a Markdown knowledge file and indexes it for RAG.
@admin_bp.route("/knowledge/markdown/new", methods=["GET", "POST"])
def create_knowledge_markdown():
    if request.method == "POST":
        filename = request.form.get("filename", "").strip()
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "General")
        content = request.form.get("content", "")
        if not filename or not content.strip():
            flash("Markdown filename and content are required.", "error")
            return redirect(url_for("admin.create_knowledge_markdown"))

        try:
            item = create_markdown_source_from_admin(
                filename=filename,
                title=title,
                category=category,
                content=content,
            )
        except Exception as exc:
            flash(f"Failed to create Markdown source: {exc}", "error")
            return redirect(url_for("admin.create_knowledge_markdown"))

        flash("Markdown source created and indexed successfully.", "success")
        return redirect(url_for("admin.knowledge"))

    return render_template(
        "knowledge_markdown_form.html",
        item=None,
        categories=["General", "Hours", "Branches", "Policies", "Offers", "Menu", "Delivery"],
    )

# Deletes a knowledge item from the database and vector store.
@admin_bp.route("/knowledge/delete/<int:item_id>", methods=["POST"])
def delete_knowledge(item_id):
    item = KnowledgeItem.query.get_or_404(item_id)
    try:
        delete_item_from_dashboard(item)
    except Exception:
        db.session.rollback()
        flash("Failed to delete knowledge item from database and vector store.", "error")
        return redirect(url_for("admin.knowledge"))
    flash("Knowledge item deleted successfully.", "success")
    return redirect(url_for("admin.knowledge"))

# Synchronizes Markdown knowledge files with the database and vector store.
@admin_bp.route("/knowledge/sync-markdown", methods=["POST"])
def sync_markdown():
    try:
        sync_all()
        flash("Markdown knowledge synchronized to database and vector store.", "success")
    except Exception as exc:
        flash(f"Markdown sync failed: {exc}", "error")
    return redirect(url_for("admin.knowledge"))

# Rebuilds the ChromaDB vector index completely (useful when migrating embedding models).
@admin_bp.route("/knowledge/rebuild-vectors", methods=["POST"])
def rebuild_vectors():
    try:
        from app.services.knowledge_sync import rebuild_vector_index
        count = rebuild_vector_index()
        flash(f"Vector index rebuilt successfully with {count} chunks indexed.", "success")
    except Exception as exc:
        flash(f"Vector rebuild failed: {exc}", "error")
    return redirect(url_for("admin.knowledge"))

def _render_chat_markdown(text: str) -> str:
    """Render markdown into clean, sanitized HTML for chat display.
    Disables raw HTML tags to prevent XSS attacks while preserving all styling.
    """
    if not text:
        return ""
    try:
        import markdown_it
        md = markdown_it.MarkdownIt("commonmark", {"html": False, "breaks": True})
        return md.render(text)
    except Exception:
        import html
        return html.escape(text).replace("\n", "<br>")

# Sends a user message through the LangGraph AI agent and returns its response.
@admin_bp.route("/agent/chat", methods=["POST"])
def agent_chat():
    data = request.get_json(silent=True) or {}
    session_id = str(data.get("session_id", "default")).strip()
    message = str(data.get("message", "")).strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    # Ensure ChatSession exists in DB so foreign key constraints on ChatMessage are satisfied
    chat_sess = ChatSession.query.filter_by(session_id=session_id).first()
    if not chat_sess:
        # Determine automatic sequential numbering e.g. "Chat 1", "Chat 2" for user-friendly UI display
        existing_count = ChatSession.query.count()
        chat_sess = ChatSession(session_id=session_id, title=f"Chat {existing_count + 1}")
        db.session.add(chat_sess)
        db.session.commit()

    # Persist user message to SQLite BEFORE graph execution to guarantee customer prompt is recorded even if agent fails
    user_msg_record = ChatMessage(
        session_id=session_id,
        role="user",
        content=message,
        html_content=None,
    )
    db.session.add(user_msg_record)
    db.session.commit()

    try:
        result = decider_run(session_id=session_id, message=message)
        reply_text = result.get("response", "")
        intent = result.get("intent", "")
        is_fallback = result.get("is_fallback", False)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    reply_html = _render_chat_markdown(reply_text)

    # Persist assistant response to SQLite and update session timestamp so active conversations appear at the top
    assistant_msg_record = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=reply_text,
        html_content=reply_html,
    )
    db.session.add(assistant_msg_record)
    chat_sess.updated_at = db.func.now()
    db.session.commit()

    return jsonify({
        "session_id": session_id,
        "message": reply_text,
        "html": reply_html,
        "intent": intent,
        "is_fallback": is_fallback,
        "tool_name": result.get("tool_name"),
        "tool_result": result.get("tool_result"),
        "history_length": len(agent_get_history(session_id)),
    })

@admin_bp.route("/agent/sessions", methods=["GET"])
def get_chat_sessions():
    """Retrieve all persisted chat sessions ordered with most recent first."""
    sessions = ChatSession.query.order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc()).all()
    # If no sessions exist yet, create Chat 1 automatically
    if not sessions:
        import uuid
        init_id = f"chat_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:5]}"
        first_sess = ChatSession(session_id=init_id, title="Chat 1")
        db.session.add(first_sess)
        db.session.commit()
        sessions = [first_sess]
    return jsonify([s.to_dict() for s in sessions])

@admin_bp.route("/agent/sessions", methods=["POST"])
def create_chat_session():
    """Create a new independent named chat session (e.g. Chat 1, Chat 2...)."""
    import uuid
    data = request.get_json(silent=True) or {}
    existing_count = ChatSession.query.count()
    custom_title = data.get("title", "").strip() or f"Chat {existing_count + 1}"
    new_id = f"chat_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:5]}"
    new_sess = ChatSession(session_id=new_id, title=custom_title)
    db.session.add(new_sess)
    db.session.commit()
    return jsonify(new_sess.to_dict()), 201

@admin_bp.route("/agent/sessions/<session_id>/messages", methods=["GET"])
def get_session_messages(session_id):
    """Retrieve all messages belonging to a chat session in chronological order."""
    sess = ChatSession.query.filter_by(session_id=session_id).first()
    if not sess:
        return jsonify({"error": "Session not found"}), 404
    msgs = [m.to_dict() for m in sess.messages]
    return jsonify({"session": sess.to_dict(), "messages": msgs})

@admin_bp.route("/agent/sessions/<session_id>", methods=["DELETE"])
def delete_chat_session(session_id):
    """
    Permanently delete a single chat conversation and its message history.
    Strictly isolated: does NOT delete customer profiles, confirmed orders,
    order items, or any other business data.
    """
    session_id = (session_id or "").strip()
    if not session_id:
        return jsonify({"error": "Session ID is required"}), 400

    sess = ChatSession.query.filter_by(session_id=session_id).first()
    if not sess:
        return jsonify({"error": "Session not found"}), 404

    try:
        from app.services.order_session import clear_draft
        from app.services.agent import clear_history

        # 1. Clear in-memory draft and agent message buffer for this session
        clear_draft(session_id)
        clear_history(session_id)

        # 2. Delete ChatSession and cascaded ChatMessages from database
        db.session.delete(sess)
        db.session.commit()

        return jsonify({
            "ok": True,
            "message": f"Conversation '{sess.title}' has been deleted.",
            "deleted_session_id": session_id,
        }), 200
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": f"Failed to delete session: {str(exc)}"}), 500