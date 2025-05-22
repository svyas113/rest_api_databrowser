import requests
import datetime
import json
import os
import uuid
import traceback
from utils import zip_session_folder, handle_path_parameters

def validate_iiq_credentials(username, password):
    """Validate IIQ credentials"""
    try:
        return {
            "username": username,
            "password": password,
            "success": True,
            "message": None
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e)
        }

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

def handle_iiq_call(api_base_url, username, password, session_id, param_values, *checkbox_values):
    """Handle IIQ API calls with parameter support"""
    if not session_id:
        session_id = str(uuid.uuid4())
    
    # Validate credentials
    cred_result = validate_iiq_credentials(username, password)
    if not cred_result["success"]:
        return (
            {"error": f"Failed to validate IIQ credentials: {cred_result['message']}"},
            None,
            session_id,
            "❌ IIQ authentication failed"
        )
    
    responses = {}
    base_save_folder = os.path.join("sessions", session_id, "IIQ")
    os.makedirs(base_save_folder, exist_ok=True)
    
    auth = (cred_result["username"], cred_result["password"])
    
    # Process selected endpoints
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
                        full_url, error = handle_path_parameters(endpoint, api_base_url, param_values)
                        if error:
                            responses[endpoint] = f"Error: {error}"
                            continue
                    else:
                        full_url = f"{api_base_url.rstrip('/')}{endpoint}"
                    
                    print(f"Calling IIQ endpoint: {full_url}")
                    
                    r = requests.get(full_url, auth=auth)
                    r.raise_for_status()
                    
                    data = r.json() if r.headers.get('content-type', '').startswith('application/json') else r.text
                    responses[endpoint] = data
                    
                    # Save response data
                    save_response_data(data, endpoint, base_save_folder)
                        
                except Exception as e:
                    responses[endpoint] = f"Error: {traceback.format_exc()}"
    
    # Create and return session zip
    zip_filename = create_session_zip(session_id)
    return responses, zip_filename, session_id, "✅ IIQ API calls complete!"

# Include save_response_data and create_session_zip functions (same as IdentityNow)