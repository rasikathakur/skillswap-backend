from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables are required")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

router = APIRouter(prefix="/api/profile", tags=["profile"])


class CreateProfileRequest(BaseModel):
    user_id: str
    name: str | None = None
    email: str | None = None
    photo: str | None = None
    department: str | None = None
    semester_year: str | None = None
    bio: str | None = None
    phone_number: str | None = None


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    photo: str | None = None
    department: str | None = None
    semester_year: str | None = None
    email: str | None = None
    bio: str | None = None
    profiles: dict | None = None
    scheduled_sessions: list | None = None
    skills: dict | None = None
    ratings_feedback: list | None = None
    phone_number: str | None = None


@router.post("/create")
async def create_or_update_profile(req: CreateProfileRequest, request: Request):
    try:
        # verify bearer token and ensure the token's user id matches req.user_id
        auth = request.headers.get('authorization') or request.headers.get('Authorization')
        if not auth or not auth.lower().startswith('bearer '):
            raise HTTPException(status_code=401, detail='Authorization header required')
        token = auth.split(' ', 1)[1].strip()
        try:
            # supabase.auth.get_user may return a dict with 'user' or an object with .user
            usr = supabase.auth.get_user(token)
            user = None
            if isinstance(usr, dict):
                user = usr.get('user') or usr.get('data') or (usr.get('session') and usr.get('session').get('user'))
            else:
                user = getattr(usr, 'user', None)
            if not user:
                raise Exception('invalid token')
            uid = user.get('id') if isinstance(user, dict) else getattr(user, 'id', None)
            if uid != req.user_id:
                raise HTTPException(status_code=403, detail='Token does not belong to provided user_id')
            # prefer email/name from auth user record; fall back to provided values
            auth_email = user.get('email') if isinstance(user, dict) else getattr(user, 'email', None)
            user_metadata = user.get('user_metadata') if isinstance(user, dict) else getattr(user, 'user_metadata', {})
            auth_name = None
            if isinstance(user_metadata, dict):
                auth_name = user_metadata.get('full_name') or user_metadata.get('name')
            if not auth_name:
                auth_name = user.get('name') if isinstance(user, dict) else getattr(user, 'name', None)
            if not auth_name:
                # some Supabase setups store full name under 'full_name' directly
                auth_name = user.get('full_name') if isinstance(user, dict) else getattr(user, 'full_name', None)
            # final fallbacks
            name_to_use = auth_name or req.name
            email_to_use = auth_email or req.email
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=401, detail='Invalid token')
        # check if a profile already exists for this user_id
        q = supabase.table('myprofile').select('*').eq('user_id', req.user_id).execute()
        if q.data:
            # update existing
            supabase.table('myprofile').update({
                'name': name_to_use,
                'email': email_to_use,
                'photo': req.photo,
                'department': req.department,
                'semester_year': req.semester_year,
                'bio': req.bio,
                'phone_number': req.phone_number,
                'updated_at': 'now()'
            }).eq('user_id', req.user_id).execute()
            return {"status": "updated", "user_id": req.user_id}

        # insert new profile
        ins = {
            'user_id': req.user_id,
            'name': name_to_use,
            'email': email_to_use,
            'photo': req.photo,
            'department': req.department,
            'semester_year': req.semester_year,
            'bio': req.bio,
            'phone_number': req.phone_number,
        }
        supabase.table('myprofile').insert(ins).execute()
        return {"status": "created", "user_id": req.user_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mentors/all")
async def get_all_mentors(query: str | None = None):
    try:
        # Fetch all profiles
        # In a real app, we would use pagination
        db_query = supabase.table('myprofile').select('*')
        
        if query:
            # Search by name (case-insensitive)
            # OR search in skills (JSONB keys)
            # Note: Supabase Python SDK or-filter can be complex with JSONB
            # We'll fetch and filter if query is provided, or use filter if simple
            
            # For simplicity and robustness with the current schema, 
            # we'll search name with ilike
            # and we'll handle the skills check in Python for better control over the JSON structure
            res = db_query.execute()
            data = res.data or []
            
            filtered = []
            q_lower = query.lower()
            for p in data:
                name = (p.get('name') or "").lower()
                skills = p.get('skills') or {}
                # skills is typically { "React": "Intermediate", "Java": "Advanced" }
                skill_names = [s.lower() for s in skills.keys()]
                
                if q_lower in name or any(q_lower in s for s in skill_names):
                    filtered.append(p)
            return {"status": "success", "mentors": filtered}
            
        res = db_query.execute()
        return {"status": "success", "mentors": res.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{user_id}")
async def get_profile(user_id: str):
    try:
        q = supabase.table('myprofile').select('*').eq('user_id', user_id).execute()
        if not q.data:
            raise HTTPException(status_code=404, detail="Profile not found")
        
        profile = q.data[0]
        
        # Calculate Rank
        rank = 0
        score_res = supabase.table("user_scores").select("total_score").eq("user_id", user_id).execute()
        if score_res.data:
            current_score = score_res.data[0]['total_score']
            # Count users with higher score
            rank_res = supabase.table("user_scores").select("user_id", count="exact").gt("total_score", current_score).execute()
            rank = (rank_res.count or 0) + 1
        
        profile['rank'] = rank if rank > 0 else "Unranked"
        profile['total_score'] = score_res.data[0]['total_score'] if score_res.data else 0

        feedback = profile.get('ratings_feedback') or []
        
        if feedback:
            # Extract distinct reviewer IDs
            reviewer_ids = list(set(f.get('id') for f in feedback if f.get('id')))
            
            if reviewer_ids:
                # Filter out invalid UUIDs to prevent 500 error
                valid_ids = []
                import uuid
                for rid in reviewer_ids:
                    try:
                        uuid.UUID(str(rid))
                        valid_ids.append(rid)
                    except ValueError:
                        pass

                if valid_ids:
                    # Fetch names in one batch
                    names_res = supabase.table('myprofile').select('user_id, name').in_('user_id', valid_ids).execute()
                    name_map = {row['user_id']: row['name'] for row in names_res.data} if names_res.data else {}
                    
                    # Enrich feedback with names
                    for f in feedback:
                        rid = f.get('id')
                        if rid in name_map:
                            f['reviewer_name'] = name_map[rid]
        
        return {"status": "success", "profile": profile}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{user_id}")
async def update_profile(user_id: str, req: UpdateProfileRequest, request: Request):
    try:
        # verify ownership
        auth = request.headers.get('authorization') or request.headers.get('Authorization')
        if not auth or not auth.lower().startswith('bearer '):
            raise HTTPException(status_code=401, detail='Authorization header required')
        token = auth.split(' ', 1)[1].strip()
        try:
            usr = supabase.auth.get_user(token)
            user = None
            if isinstance(usr, dict):
                user = usr.get('user') or usr.get('data') or (usr.get('session') and usr.get('session').get('user'))
            else:
                user = getattr(usr, 'user', None)
            if not user:
                raise Exception('invalid token')
            uid = user.get('id') if isinstance(user, dict) else getattr(user, 'id', None)
            if uid != user_id:
                raise HTTPException(status_code=403, detail='Not authorized to update this profile')
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=401, detail='Invalid token')

        payload = {k: v for k, v in req.dict().items() if v is not None}
        if not payload:
            raise HTTPException(status_code=400, detail="No fields to update")

        payload['updated_at'] = 'now()'
        supabase.table('myprofile').update(payload).eq('user_id', user_id).execute()
        return {"status": "updated", "user_id": user_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
