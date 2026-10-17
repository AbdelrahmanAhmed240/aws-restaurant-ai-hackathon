from datetime import datetime, timezone
from app.models.base import db

class Product(db.Model):
    """
    Product Model representing food items, meals, combos, and drinks on the menu.
    """
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(150), nullable=False, unique=True, index=True)
    category = db.Column(db.String(50), nullable=False, index=True)  # Meals, Sandwiches, Combos, Add-ons, Drinks
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Float, nullable=False)  # Base price in EGP
    combo_price = db.Column(db.Float, default=0.0)  # Add-on price to make it a combo (fries + drink)
    is_available = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "price": self.price,
            "combo_price": self.combo_price,
            "is_available": self.is_available,
        }

    def __repr__(self):
        return f"<Product {self.id}: {self.name} - {self.price} EGP>"