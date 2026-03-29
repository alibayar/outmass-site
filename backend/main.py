"""
OutMass — FastAPI Application
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import BACKEND_URL
from routers import auth, billing, campaigns, tracking

app = FastAPI(
    title="OutMass API",
    version="0.1.0",
    description="Mass email campaign backend for OutMass Chrome Extension",
)

# ── CORS ──
# Allow the Chrome extension origin + localhost for dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "chrome-extension://acdafphnihddolfhabbndfofheokckhl",
        "http://localhost:3000",
        "http://localhost:5173",
        BACKEND_URL,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──
app.include_router(auth.router)
app.include_router(campaigns.router)
app.include_router(tracking.router)
app.include_router(billing.router)


# ── Health Check ──
@app.get("/")
async def health_check():
    return {"status": "ok", "version": "0.1.0", "service": "outmass-api"}
