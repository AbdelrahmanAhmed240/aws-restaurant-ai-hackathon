from datetime import datetime, timezone
from app.models.base import db

class Customer(db.Model):
    """
    Customer Model representing unique customers identified primarily by normalized phone number.
    """
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    phone = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # 1-to-Many Relationship: One customer can have multiple orders
    orders = db.relationship("Order", back_populates="customer")

    def to_dict(self):
        return {
            "id": self.id,
            "phone": self.phone,
            "name": self.name,
            "address": self.address,
            "orders_count": len(self.orders),
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None
        }

    def __repr__(self):
        return f"<Customer {self.id}: {self.name} ({self.phone})>"