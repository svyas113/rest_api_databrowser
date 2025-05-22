import os
import io
import zipfile
import json
import datetime

def zip_session_folder(folder_path):
    """Create a ZIP file from a session folder"""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                full_path = os.path.join(root, file)
                arcname = os.path.relpath(full_path, folder_path)
                zf.write(full_path, arcname)
    zip_buffer.seek(0)
    return zip_buffer

def handle_path_parameters(endpoint, api_base_url, param_values):
    """Process path parameters for any endpoint"""
    params = extract_path_params(endpoint)
    if not params:
        return api_base_url.rstrip("/") + endpoint, None
    
    # Validate parameters
    missing_params = [p for p in params if p not in param_values or not param_values[p]]
    if missing_params:
        return None, f"Error: Missing required parameters: {', '.join(missing_params)}"
    
    # Replace parameters in URL
    full_url = api_base_url.rstrip("/") + endpoint
    for param in params:
        full_url = full_url.replace(f"{{{param}}}", param_values[param])
    
    return full_url, None

def extract_path_params(endpoint):
    """Extract path parameters from an endpoint URL"""
    params = []
    parts = endpoint.split('/')
    for part in parts:
        if part.startswith('{') and part.endswith('}'):
            param_name = part[1:-1]
            params.append(param_name)
    return params

def extract_query_params(endpoint_spec):
    """Extract query parameters from endpoint specification"""
    query_params = []
    parameters = endpoint_spec.get('parameters', [])
    for param in parameters:
        if param.get('in') == 'query':
            name = param.get('name')
            required = param.get('required', False)
            description = param.get('description', 'No description')
            query_params.append(('query', name, required, description))
    return query_params

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