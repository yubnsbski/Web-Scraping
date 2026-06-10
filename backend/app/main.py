import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Load environment variables from .env file
env_path = Path(__file__).resolve().parents[2] / "backend" / ".env"
load_dotenv(dotenv_path=env_path)

app = FastAPI(title="Minimal Backend Placeholder")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok", "msg": "Minimal backend placeholder"}


@app.get("/api/crypto/config")
def crypto_config():
    # Minimal stub that mirrors what the frontend expects during development
    return {"supported": ["btc", "eth"], "mode": "dev"}


@app.get("/api/encrypted-tx")
def encrypted_tx():
    return {"tx": []}


@app.post("/api/runtime/real-api")
def set_real_api(body: dict):
    """
    Set real API status. Checks for GEMINI_API_KEY environment variable.
    Development-friendly: if enabled=true and GEMINI_API_KEY exists, returns usable=true.
    In production, this should validate the key with the actual Gemini API and check budget limits.
    """
    enabled = bool(body.get("enabled"))
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    
    if enabled:
        if api_key:
            # API key is configured; allow real API usage
            return {"usable": True}
        else:
            # API key missing; return error message
            return {
                "usable": False,
                "error": "GEMINI_API_KEY environment variable is not set. "
                         "Set it before starting the backend to enable real API calls."
            }
    
    # If disabling, just acknowledge it (no API key needed)
    return {"usable": False}


@app.post("/api/rag/search")
def rag_search(body: dict):
    """Stub for RAG search."""
    return {"results": []}


@app.post("/api/orchestrate")
def orchestrate(body: dict):
    """Stub for orchestration endpoint."""
    return {"answer": "Placeholder response", "sources": []}


@app.post("/api/forecast/evaluate")
def forecast_evaluate(body: dict):
    """Stub for forecast evaluation."""
    return {"best_model": "naive", "models": []}


@app.post("/api/forecast/predict")
def forecast_predict(body: dict):
    """Stub for forecast prediction."""
    return {"predictions": []}


# Serve a lightweight static UI so developers without Node can still test the API
static_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
if static_dist.exists():
    # If the frontend has been built (web/dist), serve it at root so backend can serve the full app.
    app.mount("/", StaticFiles(directory=str(static_dist), html=True), name="frontend")
else:
    # Otherwise expose the simple developer UI at /ui
    app.mount("/ui", StaticFiles(directory="static", html=True), name="ui")
