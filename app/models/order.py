from datetime import datetime, timezone
from app.models.base import db

class Order(db.Model):
    """
    Order Model representing customer orders for delivery, pickup, or dine-in.
    """
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    order_code = db.Column(db.String(30), unique=True, nullable=False, index=True)  # e.g., "ORD-60689"
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=True)
    customer_name = db.Column(db.String(100), nullable=True)
    customer_phone = db.Column(db.String(20), nullable=True)
    order_type = db.Column(db.String(20), nullable=False, default="delivery")  # "delivery", "pickup", "dine_in"
    payment_method = db.Column(db.String(20), nullable=False, default="Cash")  # "Cash" or "Visa"
    delivery_address = db.Column(db.String(255), nullable=True)
    pickup_branch = db.Column(db.String(100), nullable=True)
    table_number = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(30), nullable=False, default="In Kitchen")  # "In Kitchen", "Ready", "Delivered", "Cancelled"
    total_price = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    customer = db.relationship("Customer", back_populates="orders")
    items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

    def items_summary(self):
        """Returns formatted item summary string: 'Shawarma x2 | Cola x1'"""
        return " | ".join([f"{item.product_name} x{item.quantity}" for item in self.items])

    def to_dict(self):
        c_name = self.customer.name if self.customer else self.customer_name
        c_phone = self.customer.phone if self.customer else self.customer_phone
        return {
            "id": self.id,
            "order_code": self.order_code,
            "customer_name": c_name,
            "customer_phone": c_phone,
            "order_type": self.order_type,
            "payment_method": self.payment_method,
            "delivery_address": self.delivery_address,
            "pickup_branch": self.pickup_branch,
            "table_number": self.table_number,
            "status": self.status,
            "total_price": self.total_price,
            "items_summary": self.items_summary(),
            "items": [item.to_dict() for item in self.items],
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S")
        }

    def __repr__(self):
        return f"<Order {self.order_code}: {self.total_price} EGP [{self.status}]>"

class OrderItem(db.Model):
    """
    OrderItem Model representing individual items inside an order.
    """
    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=True)
    product_name = db.Column(db.String(150), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Float, nullable=False)
    line_total = db.Column(db.Float, nullable=False)
    notes = db.Column(db.String(255), nullable=True)  # e.g., "Free garlic sauce, Extra spicy"

    # Relationship
    order = db.relationship("Order", back_populates="items")
    product = db.relationship("Product")

    def to_dict(self):
        return {
            "id": self.id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "line_total": self.line_total,
            "notes": self.notes
        }