from app import create_app
from config import config

# Create Flask app instance using our factory
app = create_app()

if __name__ == "__main__":
    print(f"Starting Restaurant Admin Server on http://127.0.0.1:{config.PORT}")
    app.run(host="0.0.0.0", port=config.PORT, debug=config.DEBUG, use_reloader=False)