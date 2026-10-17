from datetime import datetime, timezone
from app.models.base import db

class KnowledgeItem(db.Model):
    """
    KnowledgeItem Model storing raw RAG knowledge chunks in SQL.
    Allows the Admin Dashboard to Add, Edit, Delete, and list knowledge documents
    which are synchronized to the vector database.
    """
    __tablename__ = "knowledge_items"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(50), nullable=False, default="General")  # Menu, Branches, Hours, Policies, Offers
    content = db.Column(db.Text, nullable=False)
    # source_path links this DB record back to the Markdown file it was synced from.
    source_path = db.Column(db.String(255), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "content": self.content,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None
        }

    def __repr__(self):
        return f"<KnowledgeItem {self.id}: {self.title} [{self.category}]>"