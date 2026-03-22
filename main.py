from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from auth import router as auth_router
from game_loading import router as game_router
from game_scores import router as game_scores_router
from push import router as push_router
from myprofile import router as profile_router
from schedule import router as schedule_router
import os
import asyncio
from dotenv import load_dotenv
from urllib import request as urllib_request

load_dotenv()

app = FastAPI(
    title="Peer-to-Peer Learning API",
    description="Backend API for peer-to-peer learning platform",
    version="1.0.0"
)


KEEPALIVE_INTERVAL_DAYS = int(os.getenv("SUPABASE_KEEPALIVE_INTERVAL_DAYS", "4"))
KEEPALIVE_INTERVAL_SECONDS = KEEPALIVE_INTERVAL_DAYS * 24 * 60 * 60


async def _ping_supabase_once():
    """Best-effort ping so Supabase doesn't stay cold for long periods."""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        print("Supabase keepalive skipped: SUPABASE_URL or SUPABASE_KEY missing")
        return

    def _send_ping():
        # /auth/v1/settings is lightweight and reachable with project key headers.
        req = urllib_request.Request(
            f"{supabase_url}/auth/v1/settings",
            method="GET",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
            },
        )
        with urllib_request.urlopen(req, timeout=15) as response:
            return response.status

    try:
        status_code = await asyncio.to_thread(_send_ping)
        print(f"Supabase keepalive ping successful (status: {status_code})")
    except Exception as exc:
        print(f"Supabase keepalive ping failed: {str(exc)}")


async def _supabase_keepalive_worker():
    # Run one ping at startup, then sleep for the configured interval.
    while True:
        await _ping_supabase_once()
        await asyncio.sleep(KEEPALIVE_INTERVAL_SECONDS)


@app.on_event("startup")
async def _start_supabase_keepalive_worker():
    app.state.supabase_keepalive_task = asyncio.create_task(_supabase_keepalive_worker())


@app.on_event("shutdown")
async def _stop_supabase_keepalive_worker():
    task = getattr(app.state, "supabase_keepalive_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

# Configure CORS
origins = [
    "https://skillswap-frontend-fawn.vercel.app",
]

if os.getenv("FRONTEND_URL"):
    origins.append(os.getenv("FRONTEND_URL"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(game_router)
app.include_router(game_scores_router)
app.include_router(profile_router)
app.include_router(schedule_router)
app.include_router(push_router)


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "Peer-to-Peer Learning API is running"}


@app.get("/health")
async def health():
    """Health status endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
