import os
from pathlib import Path
from dotenv import load_dotenv

# Base Directory of the Project
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from .env file
load_dotenv(BASE_DIR / ".env")

class Config:
    """Application configuration loaded from environment variables."""
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-default")
    DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")
    PORT = int(os.getenv("PORT", 5000))

    # Database Settings
    instance_dir = BASE_DIR / "instance"
    db_path = instance_dir / "restaurant.db"

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URI",
        f"sqlite:///{db_path.as_posix()}"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # LLM Provider Priority & Configuration (Bedrock Primary, Gemini Automatic Fallback)
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "bedrock").lower()

    # Amazon Bedrock Configuration (Primary Response Provider)
    BEDROCK_ENABLED = os.getenv("BEDROCK_ENABLED", "True").lower() in ("true", "1", "yes")
    AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "eu-north-1"))
    BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
    BEDROCK_TIMEOUT = int(os.getenv("BEDROCK_TIMEOUT", "10"))
    BEDROCK_COOLDOWN_SECONDS = int(os.getenv("BEDROCK_COOLDOWN_SECONDS", "60"))

    # Google Gemini Configuration (Automatic Fallback Generative LLM & Embeddings Provider)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")

    # ChromaDB Vector Store Path
    CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", str(BASE_DIR / "data" / "chroma_db"))

    # Agent defaults for LLM usage
    AGENT_TEMPERATURE = float(os.getenv("AGENT_TEMPERATURE", "0.3"))
    AGENT_MAX_TOKENS = int(os.getenv("AGENT_MAX_TOKENS", "2048"))

    # Strands Decider 2B Execution Mode
    # DECIDER_ENABLED=True keeps Strands Decider 2B active for every normal intent classification request.
    # PRELOAD_DECIDER=False enables lazy-loading on the first request (fast server startup, zero idle memory).
    # PRELOAD_DECIDER=True loads the model during application factory startup.
    DECIDER_ENABLED = os.getenv("DECIDER_ENABLED", "True").lower() in ("true", "1", "yes")
    PRELOAD_DECIDER = os.getenv("PRELOAD_DECIDER", "True").lower() in ("true", "1", "yes")
    DECIDER_THREADS = int(os.getenv("DECIDER_THREADS", "0"))  # 0 = auto (PyTorch default)

# Active configuration instance
config = Config()
