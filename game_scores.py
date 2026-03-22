from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from supabase import create_client
import os
from datetime import datetime
from typing import Optional, List

from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/api/games", tags=["games"])

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

class GameAttemptRequest(BaseModel):
    game_id: str
    question_id: str
    coding_language: str
    level: str
    score: int
    is_correct: bool
    time_taken_seconds: Optional[int] = None

async def get_current_user_id(request: Request):
    auth = request.headers.get('authorization') or request.headers.get('Authorization')
    if not auth or not auth.lower().startswith('bearer '):
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = auth.split(' ', 1)[1].strip()
    
    usr = supabase.auth.get_user(token)
    user_data = None
    if isinstance(usr, dict):
        user_data = usr.get('user') or usr.get('data') or (usr.get('session') and usr.get('session').get('user'))
    else:
        user_data = getattr(usr, 'user', None)
        
    if not user_data:
        raise HTTPException(status_code=401, detail='Invalid token')
        
    return user_id if isinstance(user_data, dict) and (user_id := user_data.get('id')) else getattr(user_data, 'id', None)

@router.post("/attempt")
async def record_attempt(req: GameAttemptRequest, request: Request):
    user_id = await get_current_user_id(request)
    try:
        # 1. Record the attempt
        attempt_data = {
            "user_id": user_id,
            "game_id": req.game_id,
            "question_id": req.question_id,
            "coding_language": req.coding_language,
            "level": req.level,
            "is_correct": req.is_correct,
            "score": req.score,
            "time_taken_seconds": req.time_taken_seconds
        }
        print(f"Recording attempt for user {user_id}: {req}")
        supabase.table("user_game_attempts").insert(attempt_data).execute()
        print("Successfully recorded attempt in user_game_attempts")

        # 2. Update user_scores
        print(f"Fetching game name for id: {req.game_id}")
        game_res = supabase.table("games").select("name").eq("id", req.game_id).execute()
        if not game_res.data:
            print(f"Game not found for id: {req.game_id}")
            raise HTTPException(status_code=404, detail="Game not found")
        
        game_name = game_res.data[0]['name'].lower().replace(" ", "_")
        score_field = f"{game_name}_score"
        
        user_score_res = supabase.table("user_scores").select("*").eq("user_id", user_id).execute()
        
        if not user_score_res.data:
            new_scores = {
                "user_id": user_id,
                "total_score": req.score,
                score_field: req.score,
                "updated_at": datetime.utcnow().isoformat()
            }
            supabase.table("user_scores").insert(new_scores).execute()
        else:
            current = user_score_res.data[0]
            updated = {
                "total_score": (current.get("total_score") or 0) + req.score,
                score_field: (current.get(score_field) or 0) + req.score,
                "updated_at": datetime.utcnow().isoformat()
            }
            supabase.table("user_scores").update(updated).eq("user_id", user_id).execute()

        return {"status": "success"}
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/rank")
async def get_user_rank(
    request: Request,
    category: str = "global",
    game_id: str | None = None,
    language: str | None = None
):
    """
    Get the rank of the current user for a specific category.
    """
    try:
        user_id = await get_current_user_id(request)
        
        if category == "global":
            score_res = supabase.table("user_scores").select("total_score").eq("user_id", user_id).execute()
            if not score_res.data:
                return {"rank": "Unranked", "score": 0}
            current_score = score_res.data[0]['total_score']
            rank_res = supabase.table("user_scores").select("user_id", count="exact").gt("total_score", current_score).execute()
            return {"rank": (rank_res.count or 0) + 1, "score": current_score}
            
        elif category == "game" and game_id:
            score_col = None
            # Map game_id to score column
            games_res = supabase.table("games").select("name").eq("id", game_id).execute()
            if games_res.data:
                name = games_res.data[0]['name'].lower().replace(" ", "_")
                score_col = f"{name}_score"
            
            if not score_col:
                return {"rank": "Unranked", "score": 0}
                
            score_res = supabase.table("user_scores").select(score_col).eq("user_id", user_id).execute()
            if not score_res.data:
                return {"rank": "Unranked", "score": 0}
            current_score = score_res.data[0][score_col]
            rank_res = supabase.table("user_scores").select("user_id", count="exact").gt(score_col, current_score).execute()
            return {"rank": (rank_res.count or 0) + 1, "score": current_score}
            
        elif category == "language" and language:
            # Aggregated score for this language
            agg = supabase.table("user_game_attempts").select("score").eq("user_id", user_id).eq("coding_language", language).execute()
            user_total = sum(item['score'] for item in agg.data) if agg.data else 0
            
            # This is expensive, in a real app use a view/RPC
            all_agg = supabase.table("user_game_attempts").select("user_id, score").eq("coding_language", language).execute()
            totals = {}
            for item in all_agg.data:
                uid = item['user_id']
                totals[uid] = totals.get(uid, 0) + item['score']
            
            better_users = 0
            for uid, score in totals.items():
                if score > user_total:
                    better_users += 1
            
            return {"rank": better_users + 1 if user_total > 0 else "Unranked", "score": user_total}
            
        return {"rank": "Unranked", "score": 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/leaderboard")
async def get_leaderboard(category: str = "global", game_id: Optional[str] = None, language: Optional[str] = None):
    try:
        # Fetch leaderboard data joined with profiles
        # Note: In a real app, you'd use a view or RPC for joins and ranking
        # but here we'll pull data and enrich if needed.
        
        if category == "global":
            res = supabase.table("user_scores").select("user_id, total_score").order("total_score", desc=True).limit(50).execute()
        elif category == "game" and game_id:
            game_res = supabase.table("games").select("name").eq("id", game_id).execute()
            field = f"{game_res.data[0]['name'].lower().replace(' ', '_')}_score"
            res = supabase.table("user_scores").select(f"user_id, {field}").gt(field, 0).order(field, desc=True).limit(50).execute()
        elif category == "language" and language:
            # Aggregate from attempts
            res = supabase.table("user_game_attempts").select("user_id, score").eq("coding_language", language).execute()
            # Group by user_id manually if no RPC
            agg = {}
            for row in res.data:
                uid = row['user_id']
                agg[uid] = agg.get(uid, 0) + row['score']
            sorted_agg = sorted(agg.items(), key=lambda x: x[1], reverse=True)[:50]
            leaderboard_data = [{"user_id": u, "score": s} for u, s in sorted_agg]
        else:
            raise HTTPException(status_code=400, detail="Invalid filters")

        if category != "language":
            leaderboard_data = []
            for item in res.data:
                score_val = item.get("total_score") if category == "global" else item.get(field)
                leaderboard_data.append({"user_id": item["user_id"], "score": score_val})

        # Enrich with names
        uids = [x['user_id'] for x in leaderboard_data]
        if uids:
            profiles = supabase.table("myprofile").select("user_id, name, photo").in_("user_id", uids).execute()
            name_map = {p['user_id']: p for p in profiles.data}
            for entry in leaderboard_data:
                p = name_map.get(entry['user_id'], {})
                entry['name'] = p.get('name', 'Unknown')
                entry['photo'] = p.get('photo')
                entry['rank'] = leaderboard_data.index(entry) + 1

        return {"status": "success", "leaderboard": leaderboard_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
