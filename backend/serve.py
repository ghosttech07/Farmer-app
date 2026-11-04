"""Production server: waitress (works on Windows and Linux). Use this instead of `python app.py`
for the pilot or any deployment. Serves the API and, once built, the React app from frontend/dist."""
import os

from waitress import serve

from app import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"Pantha Sahayam on http://0.0.0.0:{port}")
    serve(app, host="0.0.0.0", port=port, threads=8)
