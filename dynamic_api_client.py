import requests
import json
import yaml
import argparse
import os
from urllib.parse import urljoin, urlparse

# Attempt to import ApiSchemaGeneratorV5, or define a minimal version if not found
try:
    from api_schema_generatorV5 import ApiSchemaGeneratorV5
except ImportError:
    print("Warning: api_schema_generatorV5.py not found. Using minimal local parser.")
    # Define a minimal parser if ApiSchemaGeneratorV5 is not available
    # This is a simplified version for basic functionality
    class MinimalApiParser:
        def __init__(self, api_spec_url: str):
            self.api_spec_url = api_spec_url
            self.api_spec = None
            self.servers = []
            self.security_schemes = {}
            self.global_security = []
            self.paths = {}

        def fetch_api_spec(self):
            try:
                if self.api_spec_url.startswith(('http://', 'https://')):
                    response = requests.get(self.api_spec_url)
                    response.raise_for_status()
                    content = response.text
                else:
                    with open(self.api_spec_url, 'r', encoding='utf-8') as f:
                        content = f.read()
                
                try:
                    self.api_spec = json.loads(content)
                except json.JSONDecodeError:
                    self.api_spec = yaml.safe_load(content)
                return True
            except Exception as e:
                print(f"Error fetching/parsing API specification: {e}")
                return False

        def extract_data(self):
            if not self.api_spec:
                if not self.fetch_api_spec():
                    return False
            
            self.servers = self.api_spec.get('servers', [])
            self.security_schemes = self.api_spec.get('components', {}).get('securitySchemes', {})
            self.global_security = self.api_spec.get('security', [])
            self.paths = self.api_spec.get('paths', {})
            return True

    ApiSchemaGeneratorV5 = MinimalApiParser # Use the minimal parser

def get_input(prompt_message, default_value=None):
    if default_value:
        return input(f"{prompt_message} [{default_value}]: ") or default_value
    return input(f"{prompt_message}: ")

def get_base_url(servers, api_spec_path):
    suggested_url = None
    if servers:
        # Prefer HTTPS if available
        https_server = next((s['url'] for s in servers if s['url'].startswith('https://')), None)
        if https_server:
            suggested_url = https_server.rstrip('/')
        elif servers[0].get('url'):
            suggested_url = servers[0]['url'].rstrip('/')
    
    if suggested_url:
        print(f"A server URL was found in the API specification: {suggested_url}")
        return get_input("Please enter the base API URL (e.g., https://api.example.com/v1)", default_value=suggested_url)
    else:
        if os.path.exists(api_spec_path): # Check if it's a local file to provide context for the warning
            print("Warning: No 'servers' block found in the API specification.")
        return get_input("Please enter the base API URL (e.g., https://api.example.com/v1)")

def get_auth_details(security_schemes, active_security_requirements):
    """
    Determines the authentication method and prompts user for credentials.
    Uses the first active security requirement.
    """
    auth_config = {}
    if not active_security_requirements:
        print("No active security requirements found for this endpoint/API. Proceeding without authentication.")
        return auth_config

    # Use the first security requirement listed
    first_req_name = list(active_security_requirements[0].keys())[0]
    
    if first_req_name not in security_schemes:
        print(f"Warning: Security scheme '{first_req_name}' not defined in components.securitySchemes.")
        return auth_config

    scheme = security_schemes[first_req_name]
    auth_type = scheme.get('type')
    print(f"\n--- Authentication Required: {first_req_name} ({auth_type}) ---")

    if auth_type == 'apiKey':
        auth_config['type'] = 'apiKey'
        auth_config['name'] = scheme.get('name')
        auth_config['in'] = scheme.get('in')
        auth_config['value'] = get_input(f"Enter API Key for '{auth_config['name']}' (in {auth_config['in']})")
    elif auth_type == 'http':
        http_scheme = scheme.get('scheme', '').lower()
        auth_config['type'] = 'http'
        auth_config['scheme'] = http_scheme
        if http_scheme == 'basic':
            username = get_input("Enter Basic Auth Username")
            password = get_input("Enter Basic Auth Password", "") # nosec B105
            auth_config['username'] = username
            auth_config['password'] = password
        elif http_scheme == 'bearer':
            auth_config['token'] = get_input("Enter Bearer Token")
        else:
            print(f"Unsupported HTTP scheme: {http_scheme}")
    elif auth_type == 'oauth2':
        auth_config['type'] = 'oauth2'
        # Simplified: For clientCredentials flow
        flows = scheme.get('flows', {})
        if 'clientCredentials' in flows:
            auth_config['flow'] = 'clientCredentials'
            cc_flow = flows['clientCredentials']
            auth_config['token_url'] = get_input("Enter OAuth2 Token URL", cc_flow.get('tokenUrl'))
            auth_config['client_id'] = get_input("Enter OAuth2 Client ID")
            auth_config['client_secret'] = get_input("Enter OAuth2 Client Secret", "") # nosec B105
            # Optionally, handle scopes
            # scopes_available = cc_flow.get('scopes', {})
            # if scopes_available:
            #     print("Available scopes:", scopes_available)
            #     auth_config['scope'] = get_input("Enter scopes (space-separated)", "")
            
            # Fetch token
            token_data = {
                'grant_type': 'client_credentials',
                'client_id': auth_config['client_id'],
                'client_secret': auth_config['client_secret'],
            }
            # if auth_config.get('scope'):
            #     token_data['scope'] = auth_config['scope']
            
            try:
                print(f"Attempting to fetch OAuth2 token from {auth_config['token_url']}...")
                token_res = requests.post(auth_config['token_url'], data=token_data, timeout=10)
                token_res.raise_for_status()
                auth_config['token'] = token_res.json().get('access_token')
                if auth_config['token']:
                    print("OAuth2 token obtained successfully.")
                else:
                    print("Failed to obtain OAuth2 token. Check credentials and token URL.")
                    print("Response:", token_res.text)
            except requests.exceptions.RequestException as e:
                print(f"Error obtaining OAuth2 token: {e}")
        else:
            print(f"Unsupported OAuth2 flow. Only clientCredentials supported in this script.")
    else:
        print(f"Unsupported security scheme type: {auth_type}")
    
    return auth_config

def select_endpoints(paths):
    print("\n--- Available Endpoints ---")
    endpoint_options = []
    for path, methods in paths.items():
        for method, details in methods.items():
            # We are interested in callable methods like get, post, put, delete, patch
            if method.lower() not in ['get', 'post', 'put', 'delete', 'patch', 'options', 'head', 'trace']:
                continue # Skip parameters, $ref etc. at this level
            
            summary = details.get('summary', 'No summary')
            endpoint_options.append({
                'path': path,
                'method': method.upper(),
                'details': details
            })
            print(f"{len(endpoint_options)}. {method.upper()} {path} - {summary}")

    if not endpoint_options:
        print("No callable endpoints found in the specification.")
        return []

    selected_indices_str = get_input("Enter numbers of endpoints to call (comma-separated, e.g., 1,3): ")
    selected_endpoints = []
    try:
        selected_indices = [int(i.strip()) - 1 for i in selected_indices_str.split(',')]
        for index in selected_indices:
            if 0 <= index < len(endpoint_options):
                selected_endpoints.append(endpoint_options[index])
            else:
                print(f"Warning: Invalid endpoint number {index + 1} skipped.")
    except ValueError:
        print("Invalid input for endpoint selection.")
    return selected_endpoints

def make_api_call(base_url, endpoint_info, auth_details, security_schemes):
    path = endpoint_info['path']
    method = endpoint_info['method']
    details = endpoint_info['details']

    print(f"\n--- Calling: {method} {path} ---")

    # Determine active security for this endpoint
    endpoint_security = details.get('security') # Endpoint specific
    # If not defined at endpoint, it might fall back to global, handled by `auth_details` already if it was based on global.
    # For simplicity, if endpoint_security is defined, we re-evaluate auth.
    # This part could be more sophisticated to merge/override global.
    # For now, if endpoint has `security`, we assume `auth_details` should be re-evaluated or specific.
    # However, `get_auth_details` is called once globally. A more robust system would check per endpoint.
    # Current `auth_details` is based on the *first* global or first scheme if no global.

    headers = {'Accept': 'application/json'}
    params = {}
    data = None
    json_payload = None

    # Apply authentication
    if auth_details:
        if auth_details.get('type') == 'apiKey':
            if auth_details.get('in') == 'header':
                headers[auth_details['name']] = auth_details['value']
            elif auth_details.get('in') == 'query':
                params[auth_details['name']] = auth_details['value']
        elif auth_details.get('type') == 'http':
            if auth_details.get('scheme') == 'basic' and auth_details.get('username') is not None:
                # Basic auth is handled by requests' `auth` parameter
                pass
            elif auth_details.get('scheme') == 'bearer' and auth_details.get('token'):
                headers['Authorization'] = f"Bearer {auth_details['token']}"
        elif auth_details.get('type') == 'oauth2' and auth_details.get('token'):
             headers['Authorization'] = f"Bearer {auth_details['token']}"


    # Collect parameters
    path_params = {}
    if 'parameters' in details:
        for param_spec in details['parameters']:
            # Resolve $ref if it's a reference to a component parameter
            if '$ref' in param_spec:
                ref_path = param_spec['$ref'].split('/')
                if ref_path[0] == '#' and ref_path[1] == 'components' and ref_path[2] == 'parameters':
                    param_name_ref = ref_path[3]
                    # This requires having the full spec parsed, including components.parameters
                    # The minimal parser doesn't do this deeply. ApiSchemaGeneratorV5 would.
                    # For now, assume direct definition or skip complex $refs for parameters.
                    print(f"Skipping parameter with $ref: {param_spec['$ref']} (full $ref resolution for params not in minimal script)")
                    continue # Simplified handling
                else: # Unrecognized $ref
                    print(f"Skipping parameter with unrecognized $ref: {param_spec['$ref']}")
                    continue

            param_name = param_spec.get('name')
            param_in = param_spec.get('in')
            param_required = param_spec.get('required', False)
            param_schema = param_spec.get('schema', {})
            param_type = param_schema.get('type', 'string')
            param_description = param_spec.get('description', '')
            
            prompt_msg = f"Enter value for {param_in} parameter '{param_name}' ({param_type})"
            if param_description:
                prompt_msg += f" ({param_description})"
            if param_required:
                prompt_msg += " (required)"
            
            user_value = get_input(prompt_msg, param_schema.get('default'))

            if user_value or (param_required and not user_value): # Process if value given, or if required and no value (let API validate)
                if not user_value and param_required:
                    print(f"Warning: Required parameter '{param_name}' not provided.")
                
                if param_in == 'path':
                    path_params[param_name] = user_value
                elif param_in == 'query':
                    params[param_name] = user_value
                elif param_in == 'header':
                    headers[param_name] = user_value
                # Other 'in' types (e.g., cookie) are less common for basic clients

    # Substitute path parameters
    request_path = path
    for p_name, p_val in path_params.items():
        request_path = request_path.replace(f"{{{p_name}}}", str(p_val))
    
    full_url = urljoin(base_url.rstrip('/') + '/', request_path.lstrip('/'))


    # Handle request body for POST, PUT, PATCH
    if method in ['POST', 'PUT', 'PATCH']:
        request_body_spec = details.get('requestBody')
        if request_body_spec:
            # Resolve $ref for requestBody
            if '$ref' in request_body_spec:
                ref_path = request_body_spec['$ref'].split('/')
                if ref_path[0] == '#' and ref_path[1] == 'components' and ref_path[2] == 'requestBodies':
                    # This requires full spec parsing. Minimal script won't resolve this.
                    print(f"Skipping requestBody with $ref: {request_body_spec['$ref']} (full $ref resolution not in minimal script)")
                    request_body_spec = None # Cannot proceed with this $ref
                else:
                    print(f"Skipping requestBody with unrecognized $ref: {request_body_spec['$ref']}")
                    request_body_spec = None


            if request_body_spec and 'content' in request_body_spec:
                content_types = request_body_spec['content']
                if 'application/json' in content_types:
                    headers['Content-Type'] = 'application/json'
                    # Potentially build JSON based on schema, for now, raw JSON input
                    print("This endpoint expects a JSON request body.")
                    print(f"Schema hint: {json.dumps(content_types['application/json'].get('schema', {}), indent=2)}")
                    body_str = get_input("Enter JSON body as a single line string (or leave empty):")
                    if body_str:
                        try:
                            json_payload = json.loads(body_str)
                        except json.JSONDecodeError:
                            print("Invalid JSON provided for request body. Sending as raw string if possible or failing.")
                            data = body_str # Fallback for malformed JSON, might fail
                elif 'application/x-www-form-urlencoded' in content_types:
                    headers['Content-Type'] = 'application/x-www-form-urlencoded'
                    print("This endpoint expects form data. Enter key=value pairs, one per line. End with an empty line.")
                    form_data = {}
                    while True:
                        line = get_input("key=value (or empty to finish): ")
                        if not line:
                            break
                        if '=' in line:
                            key, value = line.split('=', 1)
                            form_data[key.strip()] = value.strip()
                        else:
                            print("Invalid format. Use key=value.")
                    if form_data:
                        data = form_data
                else:
                    print(f"Unsupported request body content type: {list(content_types.keys())[0]}. Please handle manually.")

    # Make the request
    try:
        print(f"Requesting: {method} {full_url}")
        print(f"Headers: {headers}")
        if params: print(f"Query Params: {params}")
        if json_payload: print(f"JSON Payload: {json.dumps(json_payload)}")
        if data: print(f"Form Data: {data}")

        current_auth = None
        if auth_details.get('type') == 'http' and auth_details.get('scheme') == 'basic':
            current_auth = (auth_details['username'], auth_details['password'])

        response = requests.request(
            method,
            full_url,
            headers=headers,
            params=params,
            json=json_payload,
            data=data,
            auth=current_auth,
            timeout=30 
        )
        print(f"\nResponse Status: {response.status_code}")
        
        content_type = response.headers.get('Content-Type', '')
        if 'application/json' in content_type:
            try:
                print("Response JSON:")
                print(json.dumps(response.json(), indent=2))
            except json.JSONDecodeError:
                print("Response Content (not valid JSON):")
                print(response.text)
        else:
            print("Response Content:")
            print(response.text[:500] + "..." if len(response.text) > 500 else response.text)

    except requests.exceptions.RequestException as e:
        print(f"API call failed: {e}")

def main():
    parser = argparse.ArgumentParser(description="Dynamic API client based on OpenAPI specification.")
    parser.add_argument("spec_file", help="Path or URL to the OpenAPI (JSON or YAML) specification file.")
    args = parser.parse_args()

    # Use ApiSchemaGeneratorV5 if available and spec_file is a path, otherwise minimal parser
    if os.path.exists(args.spec_file) and 'MinimalApiParser' not in str(ApiSchemaGeneratorV5):
        # This assumes ApiSchemaGeneratorV5 takes api_spec_url and selected_endpoints
        # We are not using selected_endpoints here for the initial parsing.
        # The constructor of ApiSchemaGeneratorV5 is:
        # __init__(self, api_spec_url: str, api_name: str = None, selected_endpoints: List[str] = None)
        # We'll pass api_name=None and selected_endpoints=None for its internal use if any.
        api_parser = ApiSchemaGeneratorV5(api_spec_url=args.spec_file)
        api_parser.extract_api_info() # This populates self.api_spec, self.auth_info, self.endpoints etc.
        
        # Adapt ApiSchemaGeneratorV5's attributes to what this script expects
        spec_servers = api_parser.api_spec.get('servers', []) if api_parser.api_spec else []
        spec_security_schemes = api_parser.auth_info if api_parser.auth_info else {}
        # ApiSchemaGeneratorV5 doesn't directly expose global_security in a simple attribute after extract_api_info
        # It's in api_parser.api_spec.get('security', [])
        spec_global_security = api_parser.api_spec.get('security', []) if api_parser.api_spec else []
        spec_paths = api_parser.endpoints if api_parser.endpoints else {}
    else: # Minimal parser or URL
        api_parser = MinimalApiParser(args.spec_file)
        if not api_parser.extract_data():
            return
        spec_servers = api_parser.servers
        spec_security_schemes = api_parser.security_schemes
        spec_global_security = api_parser.global_security
        spec_paths = api_parser.paths

    base_api_url = get_base_url(spec_servers, args.spec_file)

    # Determine active security requirements (global first)
    # A more complex app would check endpoint-specific security overrides
    active_sec_reqs = spec_global_security
    if not active_sec_reqs and spec_security_schemes: # If no global, but schemes exist, pick first scheme
        first_scheme_name = list(spec_security_schemes.keys())[0]
        active_sec_reqs = [{first_scheme_name: []}] # Mimic structure of security requirements list
        print(f"No global security requirements in spec. Using first defined scheme: {first_scheme_name}")
    
    auth = get_auth_details(spec_security_schemes, active_sec_reqs)
    
    selected = select_endpoints(spec_paths)
    if not selected:
        print("No endpoints selected. Exiting.")
        return

    for endpoint_data in selected:
        # Note: make_api_call currently doesn't re-evaluate auth per endpoint.
        # It uses the globally determined `auth`.
        make_api_call(base_api_url, endpoint_data, auth, spec_security_schemes)

if __name__ == "__main__":
    main()
