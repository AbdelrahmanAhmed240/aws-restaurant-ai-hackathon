from datetime import datetime, timezone
from app.models.base import db

class ChatSession(db.Model):
    """
    Persistent Chat Session model for multiple independent conversations.
    Supports ChatGPT-style session naming, renaming, and isolation.
    """
    __tablename__ = "chat_sessions"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False, default="New Chat")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    draft_data = db.Column(db.Text, nullable=True)

    # Relationship to messages ordered chronologically
    messages = db.relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at.asc()",
    )

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
            "message_count": len(self.messages),
        }

class ChatMessage(db.Model):
    """
    Persistent Chat Message belonging to a specific ChatSession.
    Stores role ('user' or 'assistant'), markdown text content, and timestamp.
    """
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(db.String(100), db.ForeignKey("chat_sessions.session_id"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)  # "user" or "assistant"
    content = db.Column(db.Text, nullable=False)
    html_content = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationship
    session = db.relationship("ChatSession", back_populates="messages")

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "html": self.html_content,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }