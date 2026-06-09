from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

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


# Serve a lightweight static UI so developers without Node can still test the API
static_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
if static_dist.exists():
    # If the frontend has been built (web/dist), serve it at root so backend can serve the full app.
    app.mount("/", StaticFiles(directory=str(static_dist), html=True), name="frontend")
else:
    # Otherwise expose the simple developer UI at /ui
    app.mount("/ui", StaticFiles(directory="static", html=True), name="ui")
