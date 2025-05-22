import requests
import datetime
import json
import os
import uuid
import traceback
from utils import zip_session_folder, handle_path_parameters

def fetch_identitynow_token(api_url, grant_type, client_id, client_secret):
    """Fetch OAuth token for IdentityNow"""
    token_endpoint = api_url.rstrip("/") + "/oauth/token"
    payload = {
        'grant_type': grant_type,
        'client_id': client_id,
        'client_secret': client_secret
    }
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    try:
        response = requests.post(token_endpoint, data=payload, headers=headers)
        response.raise_for_status()
        token_data = response.json()
        access_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in", 0)
        expiry_timestamp = datetime.datetime.now(datetime.timezone.utc).timestamp() + expires_in
        return {
            "access_token": access_token,
            "expiry_timestamp": expiry_timestamp,
            "success": True,
            "message": None
        }
    except Exception as e:
        return {
            "access_token": None,
            "expiry_timestamp": None,
            "success": False,
            "message": str(e)
        }

def handle_identitynow_call(api_base_url, oauth_grant, oauth_client, oauth_secret, session_id, param_values, *checkbox_values):
    """Handle IdentityNow API calls with parameter support"""
    if not session_id:
        session_id = str(uuid.uuid4())
    
    # Get OAuth token
    token_result = fetch_identitynow_token(
        api_base_url, 
        oauth_grant, 
        oauth_client, 
        oauth_secret
    )
    
    if not token_result["success"]:
        return (
            {"error": f"Failed to get OAuth token: {token_result['message']}"},
            None,
            session_id,
            "❌ OAuth token fetch failed"
        )
    
    # Format expiry time
    expiry_dt = datetime.datetime.fromtimestamp(token_result["expiry_timestamp"], tz=datetime.timezone.utc)
    expiry_str = expiry_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    token_msg = f"✅ OAuth token received! Valid until: {expiry_str}"
    
    # Process selected endpoints
    responses = {}
    base_save_folder = os.path.join("sessions", session_id, "IdentityNow")
    os.makedirs(base_save_folder, exist_ok=True)
    
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {token_result["access_token"]}'
    }
    
    # Parse and call selected endpoints
    for selections in checkbox_values:
        if isinstance(selections, list):
            for selection in selections:
                try:
                    if " | " in selection:
                        endpoint, method_part = selection.split(" | ")
                        method = method_part.split(" - ")[0].lower()
                    else:
                        endpoint = selection
                        method = "get"
                    
                    # Handle parameter replacement if needed
                    if any(char in endpoint for char in ['{', '}']):
                        full_url, error = handle_path_parameters(endpoint, f"{api_base_url}/v3", param_values)
                        if error:
                            responses[endpoint] = f"Error: {error}"
                            continue
                    else:
                        full_url = f"{api_base_url.rstrip('/')}/v3{endpoint}"
                    
                    print(f"Calling endpoint: {full_url}")
                    
                    r = requests.get(full_url, headers=headers)
                    r.raise_for_status()
                    
                    data = r.json() if r.headers.get('content-type', '').startswith('application/json') else r.text
                    responses[endpoint] = data
                    
                    # Save response data
                    save_response_data(data, endpoint, base_save_folder)
                        
                except Exception as e:
                    responses[endpoint] = f"Error: {traceback.format_exc()}"
    
    # Create and return session zip
    zip_filename = create_session_zip(session_id)
    return responses, zip_filename, session_id, "✅ API calls complete!"

def save_response_data(data, endpoint, base_save_folder):
    """Save API response data to file"""
    safe_endpoint_name = endpoint.strip("/").replace("/", "_") or "root"
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    save_folder = os.path.join(base_save_folder, f"{safe_endpoint_name} ({timestamp})")
    os.makedirs(save_folder, exist_ok=True)
    
    filename = os.path.join(save_folder, "data.jsonl")
    with open(filename, "w", encoding="utf-8") as f:
        if isinstance(data, list):
            for item in data:
                f.write(json.dumps(item) + "\n")
        elif isinstance(data, dict):
            f.write(json.dumps(data) + "\n")
        else:
            f.write(str(data))

def create_session_zip(session_id):
    """Create ZIP file of session data"""
    session_folder = os.path.join("sessions", session_id)
    zip_file = zip_session_folder(session_folder)
    zip_filename = f"session_{session_id}.zip"
    with open(zip_filename, "wb") as f:
        f.write(zip_file.read())
    return zip_filename