from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel
from supabase import create_client
import os
import asyncio
from datetime import datetime, timedelta
from push import notify_user_by_id, notify_user_subscription
import json
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables are required")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

class ScheduleCreate(BaseModel):
    title: str
    date: str
    time: str
    participant_id: str
    participant_name: str
    participant_email: str
    role_scheduler: str

class RateSessionRequest(BaseModel):
    schedule_id: int
    rating: int
    review: str

async def send_whatsapp_notification(phone: str, message: str):
    print(f"DEBUG: Triggering WhatsApp notification to {phone}: {message}")
    await asyncio.sleep(1)
    return True

@router.post("/create")
async def create_schedule(req: ScheduleCreate, request: Request, background_tasks: BackgroundTasks):
    try:
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
            
        scheduler_id = user_data.get('id') if isinstance(user_data, dict) else getattr(user_data, 'id', None)
        scheduler_name = (user_data.get('user_metadata', {}) if isinstance(user_data, dict) else getattr(user_data, 'user_metadata', {})).get('full_name', 'Someone')

        role_participant = "mentor" if req.role_scheduler.lower() == "learner" else "learner"

        schedule_data = {
            "scheduler_id": scheduler_id,
            "participant_id": req.participant_id,
            "title": req.title,
            "date": req.date,
            "time": req.time,
            "role_scheduler": req.role_scheduler,
            "role_participant": role_participant,
            "created_at": datetime.utcnow().isoformat()
        }
        
        supabase.table('schedules').insert(schedule_data).execute()

        # Update profile stats (taught/learnt_from)
        try:
            if req.role_scheduler.lower() == "learner":
                # Scheduler is Learner, Participant is Mentor
                learner_id = scheduler_id
                mentor_id = req.participant_id
            else:
                # Scheduler is Mentor, Participant is Learner
                mentor_id = scheduler_id
                learner_id = req.participant_id

            # Increment learnt_from for learner
            l_res = supabase.table('myprofile').select('learnt_from').eq('user_id', learner_id).execute()
            if l_res.data:
                curr_l = l_res.data[0].get('learnt_from') or 0
                supabase.table('myprofile').update({'learnt_from': curr_l + 1}).eq('user_id', learner_id).execute()

            # Increment taught for mentor
            m_res = supabase.table('myprofile').select('taught').eq('user_id', mentor_id).execute()
            if m_res.data:
                curr_t = m_res.data[0].get('taught') or 0
                supabase.table('myprofile').update({'taught': curr_t + 1}).eq('user_id', mentor_id).execute()

        except Exception as stat_err:
            print(f"Failed to update profile stats: {stat_err}")

        message_to_scheduler = f"Hi {scheduler_name}, your meet '{req.title}' with {req.participant_name} is scheduled for {req.date} at {req.time}."
        message_to_participant = f"Hi {req.participant_name}, {scheduler_name} has scheduled a meet '{req.title}' with you for {req.date} at {req.time}."
        
        # WhatsApp notifications
        background_tasks.add_task(send_whatsapp_notification, "SCHEDULER_PHONE", message_to_scheduler)
        background_tasks.add_task(send_whatsapp_notification, "PARTICIPANT_PHONE", message_to_participant)

        # Web Push notifications
        background_tasks.add_task(notify_user_by_id, scheduler_id, "New Meet Scheduled", message_to_scheduler, "/schedules")
        background_tasks.add_task(notify_user_by_id, req.participant_id, "New Meet Scheduled", message_to_participant, "/schedules")

        return {"status": "success", "message": "Schedule created and notifications queued"}
    except Exception as e:
        print(f"Schedule creation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def reminder_worker():
    """Background loop to send reminders 2 minutes before a session starts."""
    while True:
        try:
            # Current time and time 2 minutes from now
            now = datetime.utcnow()
            target_time = now + timedelta(minutes=2)
            
            # Formats might vary, assuming 'YYYY-MM-DD' and 'HH:MM:SS' or 'HH:MM'
            # Based on user schema: time is 'time without time zone'
            date_str = target_time.strftime('%Y-%m-%d')
            time_str = target_time.strftime('%H:%M:00') # User example shows 18:35:00

            # Fetch schedules starting around target_time
            res = supabase.table('schedules').select('*').eq('date', date_str).eq('time', time_str).execute()
            
            for s in (res.data or []):
                msg = f"Reminder: Your session '{s['title']}' starts in 2 minutes."
                
                # Use stored push info from the row itself
                if s.get('scheduler_push'):
                    try:
                        sub = json.loads(s['scheduler_push'])
                        notify_user_subscription(sub, "Session Reminder", msg, "/dashboard")
                    except:
                        notify_user_by_id(s['scheduler_id'], "Session Reminder", msg, "/dashboard")
                else:
                    notify_user_by_id(s['scheduler_id'], "Session Reminder", msg, "/dashboard")
                    
                if s.get('participant_push'):
                    try:
                        sub = json.loads(s['participant_push'])
                        notify_user_subscription(sub, "Session Reminder", msg, "/dashboard")
                    except:
                        notify_user_by_id(s['participant_id'], "Session Reminder", msg, "/dashboard")
                else:
                    notify_user_by_id(s['participant_id'], "Session Reminder", msg, "/dashboard")
                
        except Exception as e:
            print(f"Reminder worker error: {e}")
            
        await asyncio.sleep(60) # Check every minute

@router.on_event("startup")
async def startup_event():
    asyncio.create_task(reminder_worker())

@router.get("/list")
async def list_schedules(request: Request):
    try:
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
            
        current_user_id = user_data.get('id') if isinstance(user_data, dict) else getattr(user_data, 'id', None)

        q = supabase.table('schedules').select('*').or_(f"scheduler_id.eq.{current_user_id},participant_id.eq.{current_user_id}").order('date', desc=False).order('time', desc=False).execute()
        schedules = q.data or []
        
        all_uids = set()
        for s in schedules:
            all_uids.add(s['scheduler_id'])
            all_uids.add(s['participant_id'])
        
        if not all_uids:
            return {"status": "success", "schedules": []}

        prof_res = supabase.table('myprofile').select('user_id, name, photo').in_('user_id', list(all_uids)).execute()
        prof_map = {p['user_id']: p for p in prof_res.data} if prof_res.data else {}

        enriched = []
        for s in schedules:
            sch_prof = prof_map.get(s['scheduler_id'], {})
            par_prof = prof_map.get(s['participant_id'], {})
            
            enriched.append({
                **s,
                "scheduler_name": sch_prof.get('name', 'Unknown'),
                "scheduler_photo": sch_prof.get('photo'),
                "participant_name": par_prof.get('name', 'Unknown'),
                "participant_photo": par_prof.get('photo')
            })

        return {"status": "success", "schedules": enriched}
    except Exception as e:
        print(f"List schedules error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/rate")
async def rate_session(req: RateSessionRequest, request: Request):
    try:
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
            
        current_user_id = user_data.get('id') if isinstance(user_data, dict) else getattr(user_data, 'id', None)
        
        # Fetch current user name from myprofile table
        curr_prof_res = supabase.table('myprofile').select('name').eq('user_id', current_user_id).execute()
        current_user_name = curr_prof_res.data[0].get('name', 'Someone') if curr_prof_res.data else 'Someone'

        sch_res = supabase.table('schedules').select('*').eq('id', req.schedule_id).execute()
        if not sch_res.data:
            raise HTTPException(status_code=404, detail="Schedule not found")
        
        schedule = sch_res.data[0]
        
        if schedule['scheduler_id'] == current_user_id:
            target_user_id = schedule['participant_id']
            rate_column = 'rated_by_scheduler'
        elif schedule['participant_id'] == current_user_id:
            target_user_id = schedule['scheduler_id']
            rate_column = 'rated_by_participant'
        else:
            raise HTTPException(status_code=403, detail="Not authorized to rate this session")

        # Update target user's ratings_feedback in 'myprofile'
        target_prof = supabase.table('myprofile').select('ratings_feedback').eq('user_id', target_user_id).execute()
        new_entry = {
            "id": current_user_id,
            "reviewer_name": current_user_name,
            "date": datetime.utcnow().timestamp(),
            "text": req.review,
            "mentor": target_user_id,
            "rating": req.rating,
            "schedule_id": req.schedule_id
        }

        if target_prof.data:
            feedback = target_prof.data[0].get('ratings_feedback') or []
            feedback.append(new_entry)
            supabase.table('myprofile').update({"ratings_feedback": feedback}).eq('user_id', target_user_id).execute()

        # Update current user's (reviewer) ratings_feedback as well for shared history
        current_prof = supabase.table('myprofile').select('ratings_feedback').eq('user_id', current_user_id).execute()
        if current_prof.data:
            feedback = current_prof.data[0].get('ratings_feedback') or []
            feedback.append(new_entry)
            supabase.table('myprofile').update({"ratings_feedback": feedback}).eq('user_id', current_user_id).execute()

        try:
            supabase.table('schedules').update({rate_column: True}).eq('id', req.schedule_id).execute()
        except Exception as e:
            # Column might not exist, but we still saved the feedback
            print(f"Could not update schedule record: {e}")

        return {"status": "success", "message": "Rating submitted"}
    except Exception as e:
        print(f"Rate session error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
