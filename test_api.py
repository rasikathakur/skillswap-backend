"""Test the actual API endpoint"""
import requests
import json
import os

# Test the backend endpoint
api_base_url = os.getenv("VITE_API_BASE_URL")
if not api_base_url:
    raise RuntimeError("VITE_API_BASE_URL is not set")

url = f"{api_base_url}/api/games/concept-match/load"
payload = {
    "language": "C",
    "level": "EASY"
}

try:
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        data = response.json()
        print("=== API RESPONSE ===")
        print(json.dumps(data, indent=2))
        
        if data.get('questions'):
            q = data['questions'][0]
            print("\n=== FIRST QUESTION DETAILS ===")
            print(f"ID: {q.get('id')}")
            print(f"Question: {q.get('question')}")
            print(f"Options: {q.get('options')}")
            print(f"Correct: {q.get('correct')} (type: {type(q.get('correct'))})")
            print(f"Option Mapping: {q.get('option_mapping')}")
    else:
        print(f"Error: {response.status_code}")
        print(response.text)
except Exception as e:
    print(f"Connection error: {e}")
    print("Make sure backend is running on the URL configured in VITE_API_BASE_URL")
