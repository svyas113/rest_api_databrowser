import requests
import datetime
import json
import os
import uuid
import traceback
from utils import zip_session_folder, handle_path_parameters

def validate_okta_token(api_token):
    """Validate Okta API token"""
    try:
        return {
            "access_token": api_token,
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

def handle_okta_call(api_base_url, api_token, session_id, param_values, endpoints):
    """
    Make API calls to Okta endpoints.
    
    Args:
        api_base_url: The base URL for Okta API
        api_token: The Okta API token for authentication
        session_id: Current session ID
        param_values: Dictionary of parameter values for the endpoints
        endpoints: List of endpoints to call
        
    Returns:
        Tuple of (responses, download_file, session_id, message)
    """
    # Strip trailing slashes for consistency
    api_base_url = api_base_url.rstrip('/')
    
    # Set up headers with authentication
    headers = {
        "Authorization": f"SSWS {api_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    responses = {}
    
    # Process each endpoint
    for endpoint in endpoints:
        try:
            # Apply path parameters if present
            formatted_endpoint = endpoint
            for param_name, param_value in param_values.items():
                if "{" + param_name + "}" in endpoint:
                    formatted_endpoint = formatted_endpoint.replace("{" + param_name + "}", param_value)
            
            # Build full URL
            url = f"{api_base_url}{formatted_endpoint}"
            
            # Extract query parameters for this endpoint
            query_params = {}
            for param_name, param_value in param_values.items():
                if param_name not in endpoint and param_value:  # Not a path param and has value
                    query_params[param_name] = param_value
            
            # Special handling for credential verification endpoint
            if endpoint == "/api/v1/users/me":
                try:
                    r = requests.get(url, headers=headers, timeout=30)
                    r.raise_for_status()  # This will raise an exception for 4xx/5xx status codes
                    responses[endpoint] = r.json()
                except requests.exceptions.HTTPError as e:
                    # Handle authentication errors specifically
                    if e.response.status_code in (401, 403):
                        responses[endpoint] = {"error": f"Authentication failed: {str(e)}"}
                    else:
                        responses[endpoint] = {"error": f"HTTP Error: {str(e)}"}
                except Exception as e:
                    responses[endpoint] = {"error": str(e)}
                continue
                
            # Make the API request
            r = requests.get(url, headers=headers, params=query_params, timeout=30)
            
            # Check for successful response
            if r.status_code == 200:
                try:
                    responses[endpoint] = r.json()
                except ValueError:
                    responses[endpoint] = {"error": "Invalid JSON response"}
            else:
                responses[endpoint] = {"error": f"Error {r.status_code}: {r.text}"}
                
        except requests.exceptions.RequestException as e:
            responses[endpoint] = {"error": f"Request failed: {str(e)}"}
        except Exception as e:
            responses[endpoint] = {"error": f"Error: {str(e)}"}
    
    # Create a ZIP file with the results
    if responses and not all(isinstance(resp, dict) and "error" in resp for _, resp in responses.items()):
        try:
            import tempfile
            import zipfile
            import json
            import os
            from datetime import datetime
            
            # Create a temporary directory
            temp_dir = tempfile.mkdtemp()
            zip_path = os.path.join(temp_dir, "okta_data.zip")
            
            # Create ZIP file
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for endpoint, data in responses.items():
                    # Clean endpoint name for filename
                    safe_name = endpoint.replace('/', '_').replace('{', '').replace('}', '')
                    if safe_name.startswith('_'):
                        safe_name = safe_name[1:]
                        
                    filename = f"{safe_name}.json"
                    json_data = json.dumps(data, indent=2)
                    zipf.writestr(filename, json_data)
                
                # Add metadata
                metadata = {
                    "timestamp": datetime.now().isoformat(),
                    "api_base_url": api_base_url,
                    "endpoints": endpoints,
                    "session_id": session_id or str(datetime.now().timestamp())
                }
                zipf.writestr("metadata.json", json.dumps(metadata, indent=2))
                
            return responses, zip_path, session_id, "✅ API calls completed successfully"
        except Exception as e:
            return responses, None, session_id, f"⚠️ API calls completed but export failed: {str(e)}"
    
    # Handle case where all responses are errors
    if all(isinstance(resp.get(endpoint), dict) and "error" in resp.get(endpoint, {}) for resp in [responses]):
        return responses, None, session_id, "❌ All API calls failed"
    
    return responses, None, session_id, "✅ API calls completed"

# Include save_response_data and create_session_zip functions (same as IdentityNow)