from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any
import os
from supabase import create_client, Client
from pywebpush import webpush, WebPushException
import json
from fastapi import BackgroundTasks

router = APIRouter(prefix="/api/push", tags=["push"])

from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:admin@yourapp.com")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str

class SubscriptionInfo(BaseModel):
    endpoint: str
    keys: SubscriptionKeys

class SaveSubscriptionRequest(BaseModel):
    userId: str
    subscription: SubscriptionInfo

@router.post("/save-subscription")
async def save_subscription(req: SaveSubscriptionRequest, background_tasks: BackgroundTasks):
    try:
        push_info = {
            "endpoint": req.subscription.endpoint,
            "keys": {
                "p256dh": req.subscription.keys.p256dh,
                "auth": req.subscription.keys.auth
            }
        }
        push_info_str = json.dumps(push_info)
        
        # Update most recent schedules for this user
        res1 = supabase.table("schedules").update({"scheduler_push": push_info_str}).eq("scheduler_id", req.userId).execute()
        res2 = supabase.table("schedules").update({"participant_push": push_info_str}).eq("participant_id", req.userId).execute()
        
        total_updated = len(res1.data or []) + len(res2.data or [])
        print(f"Subscription saved for user {req.userId}. Updated {total_updated} schedules.")
        
        # Send immediate test notification to confirm it works
        background_tasks.add_task(
        send_push_notification,
        push_info,
        "Notifications Active!",
        "You will now receive session reminders here.",
        "/dashboard"
    )
        
        return {
            "success": True, 
            "updated_schedules": total_updated,
            "message": "Subscription received and test notification sent."
        }
    except Exception as e:
        print(f"Error saving subscription: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def send_push_notification(subscription: Dict[str, Any], title: str, body: str, url: str = "/"):
    try:
        payload = json.dumps({
            "title": title,
            "body": body,
            "url": url
        })
        
        print(f"DEBUG: Sending webpush payload to {subscription['endpoint']}")
        webpush(
            subscription_info=subscription,
            data=payload,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_SUBJECT},
            ttl=86400
        )
        print("DEBUG: 1webpush call finished successfully.")
        return True
    except WebPushException as ex:
        print(f"Web Push error: {ex}")
        if ex.response and ex.response.status_code == 410:
            # Subscription expired/unregistered, should be removed from DB
            return False
        return False
    except Exception as e:
        print(f"General Push error: {e}")
        return False

async def notify_user_subscription(subscription_info: Dict[str, Any], title: str, body: str, url: str = "/"):
    """Send notification using a specific subscription object."""
    success = await send_push_notification(subscription_info, title, body, url)
    if not success:
        print(f"Failed to send push notification")

async def notify_user_by_id(user_id: str, title: str, body: str, url: str = "/"):
    """
    Fallback method to find user's latest subscription from schedules.
    Note: The user requested only using the 'schedules' table.
    """
    # Look for the absolute most recent subscription for this user in the schedules table
    res = supabase.table("schedules").select("scheduler_push, participant_push")\
        .or_(f"scheduler_id.eq.{user_id},participant_id.eq.{user_id}")\
        .order("created_at", desc=True).limit(1).execute()
        
    if not res.data:
        print(f"No push subscription found for user {user_id} in schedules")
        return
        
    row = res.data[0]
    push_data_str = row.get("scheduler_push") if row.get("scheduler_push") else row.get("participant_push")
    
    if not push_data_str:
        print(f"No push info in the latest schedule for user {user_id}")
        return
        
    try:
        push_info = json.loads(push_data_str)
        await notify_user_subscription(push_info, title, body, url)
    except Exception as e:
        print(f"Error parsing push info for user {user_id}: {e}")
