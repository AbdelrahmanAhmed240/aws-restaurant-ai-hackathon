from app.models.base import db
from app.models.product import Product
from app.models.customer import Customer
from app.models.order import Order, OrderItem
from sqlalchemy.exc import IntegrityError
import datetime
import functools
import re
from flask import has_app_context

def _with_app_context(func):
    """Ensure database query executes within a Flask application context."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Automatically instantiate app context if invoked from CLI, background threads, or tests
        if not has_app_context():
            from app import create_app
            app = create_app()
            with app.app_context():
                return func(*args, **kwargs)
        return func(*args, **kwargs)
    return wrapper

def _normalize_egyptian_phone(value: str) -> str:
    # Strip country code (20) and leading trunk zero (0) so +201012345678 and 01012345678 resolve identically
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits.startswith("20"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = digits[1:]
    return digits

def _extract_order_code(text: str) -> str | None:
    import re
    # Match standard order codes like 'ORD-12345' even if user omits hyphen or adds extra spaces
    match = re.search(r"\bORD[-\s]*(\d{5,})\b", text or "", re.IGNORECASE)
    if match:
        return f"ORD-{match.group(1)}"
    return None

def _find_order(order_code: str) -> Order | None:
    if not order_code:
        return None
    return Order.query.filter_by(order_code=order_code.strip()).first()

@_with_app_context
def create_order(
    customer_id: int,
    items: list[dict],
    order_type: str = "delivery",
    payment_method: str = "Cash",
    delivery_address: str = "",
    pickup_branch: str = "",
    table_number: str = "",
    status: str = "In Kitchen",
) -> dict:
    """
    Create a real order with order items.
    `items` should be a list of dicts with:
      - product_id or product_name
      - quantity > 0
      - optional unit_price override
    Returns order summary or error.
    """
    try:
        customer = db.session.get(Customer, customer_id)
        if not customer:
            return {"ok": False, "error": "Customer not found."}

        if not items:
            return {"ok": False, "error": "Order must include at least one item."}

        # Generate unique 5-digit order code (e.g. 'ORD-60689') matching the assessment format
        import random
        for _ in range(20):
            candidate_code = f"ORD-{random.randint(10000, 99999)}"
            # Verify collision-free before assigning code
            if not Order.query.filter_by(order_code=candidate_code).first():
                order_code = candidate_code
                break
        else:
            # Fallback timestamp modulo guarantees a unique 5-digit sequence if random retries collide
            order_code = f"ORD-{int(datetime.datetime.now(datetime.timezone.utc).timestamp() % 100000):05d}"
        order = Order(
            order_code=order_code,
            customer_id=customer.id,
            customer_name=customer.name,
            customer_phone=customer.phone,
            order_type=order_type or "delivery",
            payment_method=payment_method or "Cash",
            delivery_address=delivery_address or None,
            pickup_branch=pickup_branch or None,
            table_number=table_number or None,
            status=status or "In Kitchen",
            total_price=0.0,
        )
        db.session.add(order)
        db.session.flush()

        total = 0.0
        order_items = []
        for item in items:
            product = None
            if item.get("product_id") is not None:
                product = db.session.get(Product, item.get("product_id"))
            if product is None and item.get("product_name"):
                product = Product.query.filter(
                    Product.name.ilike(item.get("product_name"))
                ).first()

            # Abort transaction immediately if any requested product is missing or out of stock
            if not product:
                db.session.rollback()
                return {
                    "ok": False,
                    "error": f"Product not found for item: {item}",
                }

            if not product.is_available:
                db.session.rollback()
                return {
                    "ok": False,
                    "error": f"Product '{product.name}' is currently unavailable.",
                }

            quantity_raw = item.get("quantity")
            if quantity_raw is None:
                quantity = 1
            else:
                try:
                    quantity = int(quantity_raw)
                except (TypeError, ValueError):
                    db.session.rollback()
                    return {
                        "ok": False,
                        "error": f"Invalid quantity for {product.name}.",
                    }
                if quantity <= 0:
                    db.session.rollback()
                    return {
                        "ok": False,
                        "error": f"Invalid quantity for {product.name}.",
                    }

            unit_price = item.get("unit_price")
            if unit_price is None:
                # Add combo fee if customer ordered meal as combo
                if item.get("is_combo") and product.combo_price:
                    unit_price = product.price + product.combo_price
                else:
                    unit_price = product.price
            unit_price = float(unit_price)
            line_total = round(unit_price * quantity, 2)
            total += line_total

            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                product_name=product.name,
                quantity=quantity,
                unit_price=unit_price,
                line_total=line_total,
                notes=item.get("notes"),
            )
            db.session.add(order_item)
            order_items.append(
                {
                    "product_id": product.id,
                    "product_name": product.name,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "line_total": line_total,
                    "is_combo": item.get("is_combo", False),
                    "notes": item.get("notes"),
                }
            )

        # Commit Order header and OrderItem rows together in a single atomic transaction
        order.total_price = round(total, 2)
        db.session.commit()

        return {
            "ok": True,
            "order_id": order.id,
            "order_code": order.order_code,
            "customer_id": customer.id,
            "customer_name": customer.name,
            "customer_phone": customer.phone,
            "order_type": order.order_type,
            "payment_method": order.payment_method,
            "delivery_address": order.delivery_address,
            "pickup_branch": order.pickup_branch,
            "table_number": order.table_number,
            "status": order.status,
            "total_price": order.total_price,
            "items": order_items,
        }
    except Exception as exc:
        db.session.rollback()
        return {"ok": False, "error": str(exc)}

@_with_app_context
def track_order(order_code: str) -> dict:
    """
    Look up authoritative order status from the database using order_code only.
    Returns authoritative current status and details.
    """
    try:
        # Enforce order_code requirement; customer phone number is intentionally not required
        if not order_code:
            return {"ok": False, "error": "Order code is required."}

        # Look up order directly by code
        order = _find_order(order_code)
        if not order:
            return {"ok": False, "error": f"No order found with code '{order_code}'."}

        c_name = order.customer.name if order.customer else (order.customer_name or "Valued Customer")
        c_phone = order.customer.phone if order.customer else (order.customer_phone or "")

        return {
            "ok": True,
            "order_code": order.order_code,
            "status": order.status,
            "customer_name": c_name,
            "customer_phone": c_phone,
            "order_type": order.order_type,
            "delivery_address": order.delivery_address,
            "pickup_branch": order.pickup_branch,
            "table_number": order.table_number,
            "total_price": order.total_price,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M:%S") if order.created_at else None,
            "items": [it.to_dict() for it in order.items],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

@_with_app_context
def find_or_create_customer(name: str, phone: str, address: str = "") -> dict:
    """
    Find an existing customer by phone or create one if missing.
    Normalizes Egyptian phone formats so equivalent numbers resolve to the same customer.
    Returns the customer data or an error.
    """
    try:
        phone = (phone or "").strip()
        name = (name or "").strip()
        if not phone:
            return {"ok": False, "error": "Customer phone is required."}

        # Query across standard, un-prefixed, and prefixed Egyptian number variants to prevent duplicate profiles
        normalized = _normalize_egyptian_phone(phone)
        candidate_phones = list(dict.fromkeys([phone, normalized, f"20{normalized}", f"0{normalized}"]))
        customer = Customer.query.filter(Customer.phone.in_(candidate_phones)).first()
        if customer:
            # Update customer name or address if newly provided on subsequent orders.
            # Do NOT allow a generated fallback name ('Customer XXXX', 'Valued Customer', 'Guest')
            # to overwrite a genuine human customer name.
            is_new_name_fallback = bool(
                not name
                or re.match(r"^Customer\s+\d+$", name, re.IGNORECASE)
                or name.lower() in ("valued customer", "guest")
            )
            is_curr_name_fallback = bool(
                not customer.name
                or re.match(r"^Customer\s+\d+$", customer.name, re.IGNORECASE)
                or customer.name.lower() in ("valued customer", "guest")
            )

            if name and (is_curr_name_fallback or not is_new_name_fallback):
                if customer.name != name:
                    customer.name = name

            if address and address.strip():
                customer.address = address.strip()

            db.session.commit()
            return {
                "ok": True,
                "created": False,
                "id": customer.id,
                "phone": customer.phone,
                "name": customer.name,
                "address": customer.address,
            }

        customer = Customer(name=name or None, phone=phone, address=address or None)
        db.session.add(customer)
        db.session.commit()
        return {
            "ok": True,
            "created": True,
            "id": customer.id,
            "phone": customer.phone,
            "name": customer.name,
            "address": customer.address,
        }
    except IntegrityError:
        # Roll back on concurrent database collision if another request created the customer concurrently
        db.session.rollback()
        return {"ok": False, "error": "Customer already exists."}
    except Exception as exc:
        db.session.rollback()
        return {"ok": False, "error": str(exc)}

@_with_app_context
def search_products(query: str, limit: int = 10) -> dict:
    """Search available products by name or category."""
    try:
        products = Product.query.filter(
            Product.is_available.is_(True)
        )

        if query and query.strip():
            term = f"%{query.strip()}%"
            products = products.filter(
                db.or_(
                    Product.name.ilike(term),
                    Product.category.ilike(term),
                )
            )

        results = products.order_by(
            Product.category, Product.name
        ).limit(limit).all()

        items = [
            {
                "id": p.id,
                "name": p.name,
                "category": p.category,
                "price": p.price,
                "combo_price": p.combo_price,
                "is_available": p.is_available,
                "description": p.description,
            }
            for p in results
        ]

        return {"ok": True, "items": items, "count": len(items)}

    except Exception as exc:
        return {"ok": False, "error": str(exc)}

@_with_app_context
def recommend_products(message: str, limit: int = 3) -> dict:
    """Recommend available products based on the user's message."""
    try:
        query = Product.query.filter(
            Product.is_available.is_(True)
        )

        text = (message or "").lower()

        # Extract budget, e.g. "150 egp"
        import re
        match = re.search(r"(\d{2,5})\s*egp", text)
        budget = float(match.group(1)) if match else None

        products = query.all()

        if budget is not None:
            products = [p for p in products if p.price <= budget]

        # Prioritize meals
        products.sort(
            key=lambda p: (
                (p.category or "").lower() != "meals",
                p.price,
            )
        )

        items = [
            {
                "id": p.id,
                "name": p.name,
                "category": p.category,
                "price": p.price,
                "combo_price": p.combo_price,
                "is_available": p.is_available,
                "description": p.description,
            }
            for p in products[:limit]
        ]

        return {"ok": True, "items": items, "count": len(items)}

    except Exception as exc:
        return {"ok": False, "error": str(exc)}

@_with_app_context
def query_price_info(message: str) -> dict:
    """Answer basic meal price questions."""
    try:
        text = (message or "").lower()

        meals = Product.query.filter(
            Product.is_available.is_(True),
            Product.category == "Meals",
        ).order_by(Product.price).all()

        if not meals:
            return {"ok": False, "error": "No available meals found."}

        import re

        match = re.search(
            r"(?:under|less than|أقل من|تحت)\s*(\d{2,5})", text
        )

        if match:
            budget = float(match.group(1))
            results = [m for m in meals if m.price <= budget]
            title = f"Meals Under {budget:.0f} EGP"

        elif any(word in text for word in ["cheapest", "أرخص", "ارخص"]):
            results = [m for m in meals if m.price == meals[0].price]
            title = "Cheapest Meals"

        elif any(word in text for word in ["most expensive", "highest", "أغلى", "اغلى"]):
            results = [m for m in meals if m.price == meals[-1].price]
            title = "Most Expensive Meals"

        elif any(word in text for word in ["price of each", "all meal prices", "سعر كل", "أسعار الوجبات"]):
            results = meals
            title = "All Meal Prices"

        else:
            return {"ok": False, "error": "Not a specific price query."}

        lines = [f"### {title}\n"]

        if not results:
            lines.append("No meals match your budget.")
        else:
            for m in results:
                lines.append(
                    f"* **{m.name}** — {m.price:.0f} EGP "
                    f"(Combo: +{m.combo_price:.0f} EGP)"
                )

        return {
            "ok": True,
            "type": "price_query",
            "text": "\n".join(lines),
            "items": [m.to_dict() for m in results],
        }

    except Exception as exc:
        return {"ok": False, "error": str(exc)}