from flask import Flask
from config import config
from app.models.base import db

def create_app(test_config=None):
    """
    Application Factory Pattern:
    Creates and configures the Flask application instance.
    """
    app = Flask(__name__)

    # Load configuration from config.py
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = config.SQLALCHEMY_DATABASE_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = config.SQLALCHEMY_TRACK_MODIFICATIONS
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    if test_config:
        app.config.update(test_config)

    # Initialize extensions with this app
    db.init_app(app)

    with app.app_context():
        db.create_all()

    # Register Blueprints (Route modules)
    from app.routes.admin import admin_bp
    app.register_blueprint(admin_bp)

    # Configure Strands Decider 2B mode (lightweight dev mode vs full neural routing)
    decider_enabled = app.config.get("DECIDER_ENABLED", config.DECIDER_ENABLED)
    preload_decider = app.config.get("PRELOAD_DECIDER", config.PRELOAD_DECIDER)

    from app.services.decider import set_decider_disabled
    set_decider_disabled(not decider_enabled)

    if decider_enabled and preload_decider and not app.config.get("TESTING", False):
        from app.services.decider import get_decider_engine
        engine = get_decider_engine()
        if engine is None:
            raise RuntimeError(
                "Strands Decider 2B initialization failed during application startup preload. "
                "Server startup aborted to prevent serving requests without required neural routing."
            )

    return app