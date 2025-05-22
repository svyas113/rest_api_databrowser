import requests
import yaml
import json
import zipfile
import io
import tempfile
from identityNow import handle_identitynow_call
from okta import handle_okta_call
from iiq import handle_iiq_call
from utils import extract_path_params, extract_query_params
import gradio as gr
import os
from dotenv import load_dotenv
from pathlib import Path
from api_schema_generatorV5 import ApiSchemaGeneratorV5

# Load environment variables
script_dir = Path(__file__).resolve().parent
env_path = script_dir / '.env'
load_dotenv(dotenv_path=env_path)

def fetch_api_endpoints_yaml(spec_url):
    try:
        response = requests.get(spec_url)
        response.raise_for_status()
        content = response.text
        api_spec = yaml.safe_load(content)
    except Exception as e:
        print(f"Error fetching/parsing YAML spec from {spec_url}: {e}")
        return {}
    
    endpoints = {}
    if "paths" not in api_spec:
        print("No endpoints found in the specification.")
        return {}
    
    valid_methods = ['get', 'post']  # Only process GET and POST endpoints
    for path, methods in api_spec["paths"].items():
        endpoints[path] = {}
        if not methods or not isinstance(methods, dict):
            continue
        
        common_params = methods.get("parameters", [])
        for method, details in methods.items():
            if method.lower() not in valid_methods:
                continue
            
            method_params = details.get("parameters", [])
            all_params = common_params + method_params
            endpoint_info = {
                "summary": details.get("summary", ""),
                "description": details.get("description", ""),
                "parameters": all_params
            }
            endpoints[path][method.lower()] = endpoint_info
    return endpoints

def fetch_api_endpoints_json(spec_url):
    try:
        response = requests.get(spec_url)
        response.raise_for_status()
        api_spec = response.json()
    except Exception as e:
        print(f"Error fetching/parsing JSON spec from {spec_url}: {e}")
        return {}
    
    endpoints = {}
    if "paths" not in api_spec:
        print("No endpoints found in the specification.")
        return {}
    
    valid_methods = ['get', 'post']  # Only process GET and POST endpoints
    for path, methods in api_spec["paths"].items():
        endpoints[path] = {}
        if not methods or not isinstance(methods, dict):
            continue
        
        common_params = methods.get("parameters", [])
        for method, details in methods.items():
            if method.lower() not in valid_methods:
                continue
            
            method_params = details.get("parameters", [])
            all_params = common_params + method_params
            endpoint_info = {
                "summary": details.get("summary", ""),
                "description": details.get("description", ""),
                "parameters": all_params
            }
            endpoints[path][method.lower()] = endpoint_info
    return endpoints

def get_endpoints(spec_choice, base_url=None):
    # If base_url is provided, use it directly
    if base_url:
        spec_url = base_url
        if "JSON" in spec_choice:
            return fetch_api_endpoints_json(spec_url), spec_url
        return fetch_api_endpoints_yaml(spec_url), spec_url
    
    # Otherwise, try to use environment variables as fallback
    api_spec_options = {
        "Okta (JSON)": os.getenv("OKTA_API_SPEC"),
        "SailPoint IdentityNow (YAML)": os.getenv("IDENTITY_NOW_API_SPEC"),
        "Sailpoint IIQ (YAML)": os.getenv("IIQ_API_SPEC")
    }
    spec_url = api_spec_options.get(spec_choice)
    if not spec_url:
        print(f"No API specification URL found for {spec_choice}")
        return {}, None
    
    if "JSON" in spec_choice:
        return fetch_api_endpoints_json(spec_url), spec_url
    return fetch_api_endpoints_yaml(spec_url), spec_url

def group_endpoints(endpoints, spec_choice, endpoint_type='get'):
    """Group endpoints by their first path segment, filtering by endpoint type"""
    groups = {}
    if endpoint_type == 'all':
        # For 'all' type, include all endpoints regardless of method
        if spec_choice == "Okta (JSON)":
            for path, methods in endpoints.items():
                clean_path = path.replace('/api/v1/', '')
                segments = clean_path.strip("/").split("/")
                group_key = segments[0] if segments else "other"
                if group_key not in groups:
                    groups[group_key] = {}
                groups[group_key][path] = methods
        else:
            for path, methods in endpoints.items():
                segments = path.strip("/").split("/")
                group_key = segments[0] if segments[0] != "" else "other"
                if group_key not in groups:
                    groups[group_key] = {}
                groups[group_key][path] = methods
    else:
        # For specific method types (get, post)
        if spec_choice == "Okta (JSON)":
            for path, methods in endpoints.items():
                if endpoint_type not in methods:
                    continue
                    
                clean_path = path.replace('/api/v1/', '')
                segments = clean_path.strip("/").split("/")
                group_key = segments[0] if segments else "other"
                if group_key not in groups:
                    groups[group_key] = {}
                groups[group_key][path] = methods
        else:
            for path, methods in endpoints.items():
                if endpoint_type not in methods:
                    continue
                    
                segments = path.strip("/").split("/")
                group_key = segments[0] if segments[0] != "" else "other"
                if group_key not in groups:
                    groups[group_key] = {}
                groups[group_key][path] = methods
    return groups

def generate_schema_files(api_choice_val, selected_endpoints, api_spec_url, custom_name=None):
    """Generate JSON and XML schema files for selected endpoints"""
    # Determine API name based on choice
    if api_choice_val == "Others" and custom_name:
        api_name = custom_name.lower().replace(" ", "_")
    else:
        api_name = api_choice_val.split(" (")[0].lower().replace(" ", "_")
    
    # Debug print to verify api_spec_url is not empty
    print(f"API Choice: {api_choice_val}")
    print(f"API Spec URL: {api_spec_url}")
    print(f"Selected endpoints count: {len(selected_endpoints)}")
    print(f"Using API name: {api_name}")
    
    # Create schema generator with path+method pairs
    generator = ApiSchemaGeneratorV5(api_spec_url, api_name=api_name, selected_endpoints=selected_endpoints)
    
    # Generate files in memory
    meta_data = generator.generate_datasource_plugin_meta()
    schema_xml = generator.generate_default_schema()
    
    # Create JSON string
    json_str = json.dumps(meta_data, indent=2)
    
    # Create a zip file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr(f"{api_name}_datasource_plugin_meta.json", json_str)
        zip_file.writestr(f"{api_name}_default_schema.orx", schema_xml)
    
    zip_buffer.seek(0)
    
    # Return both the individual files and the zip
    return {
        "json": json_str,
        "xml": schema_xml,
        "zip": zip_buffer
    }

def update_api_url(api_choice_val):
    global current_api_spec_url
    
    if api_choice_val == "Others":
        # For "Others", we don't set a URL yet - user will input it
        current_api_spec_url = ""
        return gr.update(visible=True), gr.update(value=""), gr.update(value="")
    
    # Get URL from environment variables
    api_spec_options = {
        "Okta (JSON)": os.getenv("OKTA_API_SPEC"),
        "SailPoint IdentityNow (YAML)": os.getenv("IDENTITY_NOW_API_SPEC"),
        "Sailpoint IIQ (YAML)": os.getenv("IIQ_API_SPEC")
    }
    
    url = api_spec_options.get(api_choice_val, "")
    print(f"Setting API spec URL to: {url}")  # Debug print
    
    # Update the global variable
    current_api_spec_url = url
    
    return gr.update(visible=False), gr.update(value=url), gr.update(value=url)  # Update both text field and state

# ----------------------------- CSS -----------------------------
custom_css = """
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap');
@import url('https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css');

body, .gradio-container {
    font-family: 'Roboto', sans-serif;
    background: #f3f3f3;
    color: #333;
    margin: 0;
    padding: 0;
}

.title {
    text-align: center;
    margin: 40px 0;
    font-size: 2.5em;
    color: #222;
    animation: fadeIn 1s ease-in;
}

.api-cards {
    display: flex;
    justify-content: center;
    gap: 30px;
    margin-bottom: 40px;
    animation: slideUp 0.5s ease-out;
}

.api-card {
    background: white;
    padding: 30px;
    border-radius: 15px;
    box-shadow: 0 6px 12px rgba(0,0,0,0.1);
    text-align: center;
    cursor: pointer;
    transition: transform 0.3s, box-shadow 0.3s;
    width: 220px;
}

.api-card:hover {
    transform: translateY(-10px);
    box-shadow: 0 8px 16px rgba(0,0,0,0.15);
}

.api-card i {
    font-size: 40px;
    color: #007BFF;
    margin-bottom: 15px;
}

.api-card h2 {
    font-size: 20px;
    margin: 15px 0;
    font-weight: 500;
}

.api-card p {
    font-size: 16px;
    color: #666;
}

.cred-section {
    background: white;
    padding: 30px;
    border-radius: 15px;
    box-shadow: 0 6px 12px rgba(0,0,0,0.1);
    margin-bottom: 30px;
    animation: fadeIn 0.5s ease-in;
}

.action-btn {
    background-color: #007BFF;
    color: white;
    border: none;
    padding: 12px 24px;
    border-radius: 8px;
    cursor: pointer;
    transition: background-color 0.3s, transform 0.2s;
    font-size: 16px;
}

.action-btn:hover {
    background-color: #0056b3;
    transform: translateY(-2px);
}

.loading-spinner {
    border: 4px solid #f3f3f3;
    border-top: 4px solid #3498db;
    border-radius: 50%;
    width: 40px;
    height: 40px;
    animation: spin 1s linear infinite;
    margin: 20px auto;
}

.loading-text {
    color: black;
    font-size: 24px;
    font-weight: bold;
    margin-top: 20px;
    text-shadow: 1px 1px 3px rgba(0, 0, 0, 0.8);
}

.fetch-loading-indicator {
    display: flex;
    justify-content: center;
    align-items: center;
    height: 100px;
}

.fetch-loading-indicator .loading-spinner {
    border-width: 6px;
    width: 50px;
    height: 50px;
}

@keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}

.success-message, .error-message {
    padding: 15px;
    border-radius: 8px;
    margin-top: 15px;
    display: flex;
    align-items: center;
    gap: 10px;
    animation: slideIn 0.3s ease-out;
    font-size: 16px;
}

.success-message {
    background: #d4edda;
    color: #155724;
}

.error-message {
    background: #f8d7da;
    color: #721c24;
}

.endpoints-section, .param-group, .fetch-section, .results-section {
    background: white;
    padding: 30px;
    border-radius: 15px;
    box-shadow: 0 6px 12px rgba(0,0,0,0.1);
    margin-bottom: 30px;
    animation: fadeIn 0.5s ease-in;
}

.custom-accordion {
    border: 1px solid #ddd;
    border-radius: 8px;
    margin-bottom: 15px;
    transition: all 0.3s ease;
}

.custom-accordion .gr-accordion-header {
    background: #f9f9f9;
    padding: 15px;
    cursor: pointer;
    font-weight: 500;
    font-size: 18px;
    transition: background-color 0.3s;
}

.custom-accordion .gr-accordion-header:hover {
    background-color: #e9ecef;
}

.custom-checkbox .gr-checkbox-group {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 15px;
}

.custom-checkbox .gr-checkbox-group label {
    font-size: 16px;
    color: #333;
    transition: color 0.3s;
}

.custom-checkbox .gr-checkbox-group label:hover {
    color: #007BFF;
}

.reset-btn {
    background-color: #6c757d;
    color: white;
    border: none;
    padding: 10px 20px;
    border-radius: 8px;
    cursor: pointer;
    transition: background-color 0.3s, transform 0.2s;
    font-size: 16px;
}

.reset-btn:hover:enabled {
    background-color: #5a6268;
    transform: translateY(-2px);
}

.gr-code {
    background: #f9f9f9;
    padding: 15px;
    border: 1px solid #ddd;
    border-radius: 8px;
    max-height: 500px;
    overflow: auto;
    font-family: 'Courier New', monospace;
    font-size: 14px;
    white-space: pre-wrap;
    word-wrap: break-word;
}

.gr-code pre {
    margin: 0;
    padding: 0;
    white-space: pre-wrap;
    word-wrap: break-word;
}

.download-btn {
    background-color: #28a745;
    color: white;
    border: none;
    padding: 12px 24px;
    border-radius: 8px;
    cursor: pointer;
    transition: background-color 0.3s, transform 0.2s;
    font-size: 16px;
}

.download-btn:hover {
    background-color: #218838;
    transform: translateY(-2px);
}

.banner {
    background-color: #007BFF;
    color: white;
    padding: 25px;
    text-align: center;
    font-size: 28px;
    font-weight: 500;
    margin-bottom: 30px;
    box-shadow: 0 4px 8px rgba(0,0,0,0.1);
}

.param-item {
    background: #f9f9f9;
    padding: 15px;
    border-radius: 8px;
    margin-bottom: 15px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}

.param-group .gr-textbox {
    border: 1px solid #ddd;
    border-radius: 8px;
    padding: 10px;
    font-size: 16px;
    transition: border-color 0.3s;
}

.param-group .gr-textbox:focus {
    border-color: #007BFF;
    box-shadow: 0 0 5px rgba(0,123,255,0.5);
}

.fetch-loading-indicator {
    display: flex;
    justify-content: center;
    align-items: center;
    height: 100px;
}

.fetch-loading-indicator .loading-spinner {
    border-width: 6px;
    width: 50px;
    height: 50px;
}

.endpoint-type-selector {
    margin-bottom: 20px;
    padding: 15px;
    background: #333333;
    border-radius: 8px;
    border: 1px solid #ddd;
}

.endpoint-type-selector label {
    color: white !important;
    font-weight: bold !important;
    font-size: 18px !important;
}

.endpoint-type-selector > .block > label:first-child {
    color: #000000;
    font-weight: 700;
    font-size: 18px;
}

.endpoint-type-selector .gr-radio-group label {
    color: white;
    font-weight: 500;
}

@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}

@keyframes slideUp {
    from { transform: translateY(30px); opacity: 0; }
    to { transform: translateY(0); opacity: 1; }
}

@keyframes slideIn {
    from { transform: translateX(-30px); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
}

.user-guide-overlay {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0,0,0,0.6);
    z-index: 9998;
    transition: all 0.5s ease;
}

.user-guide-modal {
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    background: #ffffff;
    color: #333333;
    padding: 35px;
    border-radius: 10px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.2);
    width: 80%;
    max-width: 650px;
    max-height: 80vh;
    overflow-y: auto;
    z-index: 9999;
    transition: all 0.5s ease;
    font-family: 'Roboto', sans-serif;
    font-size: 16px;
    line-height: 1.6;
}

.user-guide-modal h2,
.user-guide-modal h3,
.user-guide-modal p,
.user-guide-modal ul,
.user-guide-modal li {
    color: #333333;
}

.user-guide-modal h2 {
    color: #1a1a1a;
    font-size: 24px;
    margin-bottom: 20px;
}

.user-guide-modal h3 {
    color: #0056b3;
    font-size: 20px;
    margin-top: 25px;
}

.user-guide-modal strong {
    color: #1a1a1a;
}

.collapsed {
    opacity: 0;
    transform: translate(-50%, -50%) scale(0.9);
}
"""

with gr.Blocks(css=custom_css) as demo:
    gr.HTML("<div class='banner'>Data Connector Demo</div>")
    
    # User Guide Modal
    user_guide_html = gr.HTML("""
<div id="user-guide-overlay" class="user-guide-overlay"></div>
<div id="user-guide-modal" class="user-guide-modal">
  <h2>Data Connector - User Guide</h2>
  <p>Welcome to Data Connector, a tool that helps you easily extract and explore data from any API platform and generate schema files.</p>

  <h3>Getting Started</h3>
  <p><strong>Step 1: Select an API Platform</strong><br/>
  Click on one of the three available platforms:<br/>
  Okta: For Okta Identity Cloud data<br/>
  SailPoint IdentityNow: For cloud-based identity governance data<br/>
  SailPoint IIQ: For on-premise identity governance data<br/>
  Others: For custom API specifications</p>

  <p><strong>Step 2: Enter API Specification URL</strong><br/>
  Enter the URL for the API specification (OpenAPI/Swagger) for your selected platform.</p>

  <p><strong>Step 3: Load API Specification</strong><br/>
  Click the "Load API Specification" button to fetch and parse the API endpoints.</p>

  <p><strong>Step 4: Select Endpoint Type</strong><br/>
  Choose between GET or POST endpoints to display.</p>

  <p><strong>Step 5: Browse and Select Endpoints</strong><br/>
  After loading, you'll see API endpoints grouped by category<br/>
  Click on any category to expand it and see available endpoints<br/>
  Select the checkboxes next to the endpoints you want to include<br/>
  You can select multiple endpoints across different categories</p>

  <p><strong>Step 6: Generate Schema</strong><br/>
  Click the "Generate Schema" button to create schema files based on your selected endpoints.</p>

  <p><strong>Step 7: View and Download Results</strong><br/>
  Results will display in both JSON and XML formats<br/>
  Review the generated schema files<br/>
  Click the download button to save all files as a ZIP file</p>

  <h3>Tips and Troubleshooting</h3>
  <ul>
    <li><strong>API Specification URLs:</strong> Always include the full URL with https:// prefix</li>
    <li><strong>No Endpoints Found:</strong> Check that the API specification is valid and accessible</li>
    <li><strong>Schema Generation:</strong> Make sure to select at least one endpoint before generating schemas</li>
  </ul>

  <h3>Need Help?</h3>
  <p>If you need assistance or encounter issues, refer to the official API documentation for detailed guidance:</p>
  <ul>
    <li><strong>SailPoint IdentityNow:</strong> <a href="https://developer.sailpoint.com/docs/api/v3/identity-security-cloud-v-3-api" target="_blank">Identity Security Cloud V3 API</a></li>
    <li><strong>SailPoint IIQ:</strong> <a href="https://developer.sailpoint.com/docs/api/iiq/identityiq-scim-rest-api/" target="_blank">IdentityIQ SCIM REST API</a></li>
    <li><strong>Okta:</strong> <a href="https://developer.okta.com/docs/reference/core-okta-api/" target="_blank">Core Okta API</a></li>
  </ul>

  <p><strong style="color: #222222; font-style: italic;">You can always access these instructions any time by clicking on the "User Guide" button.</strong></p>

  <button class="action-btn" 
    onclick="
      var modal = document.getElementById('user-guide-modal');
      var overlay = document.getElementById('user-guide-overlay');
      modal.classList.add('collapsed');
      overlay.classList.add('collapsed');
      setTimeout(function(){
          modal.style.display = 'none';
          overlay.style.display = 'none';
          document.getElementById('user-guide-button').style.display = 'block';
      }, 500);
    "
  >
    I Understand, Continue
  </button>
</div>

<button id="user-guide-button" class="action-btn" 
  style="position: fixed; bottom: 20px; right: 20px; display: none; z-index: 9999; box-shadow: 0 4px 10px rgba(0,0,0,0.3);"
  onclick="
    var modal = document.getElementById('user-guide-modal');
    var overlay = document.getElementById('user-guide-overlay');
    modal.style.display = 'block';
    overlay.style.display = 'block';
    setTimeout(function(){
      modal.classList.remove('collapsed');
      overlay.classList.remove('collapsed');
    }, 100);
  "
>
  User Guide
</button>
""", visible=True)

    # State variables
    locked_endpoints_state = gr.State([])
    endpoint_type_state = gr.State("get")  # Default to GET endpoints
    api_spec_url_state = gr.State("")
    required_params_count = gr.State(0)

    # API selection with card-style UI
    api_options = [
        {"icon": "fa-cloud", "title": "Okta", "description": "Identity and Access Management", "value": "Okta (JSON)"},
        {"icon": "fa-user-shield", "title": "SailPoint IdentityNow", "description": "Cloud Identity Governance", "value": "SailPoint IdentityNow (YAML)"},
        {"icon": "fa-network-wired", "title": "Sailpoint IIQ", "description": "On-premise Identity Governance", "value": "Sailpoint IIQ (YAML)"},
        {"icon": "fa-cogs", "title": "Other", "description": "Custom API Specification", "value": "Others"}
    ]
    
    # Create a radio button with custom styling to look like cards
    choices = [(opt["title"], opt["value"]) for opt in api_options]
    api_choice = gr.Radio(choices=choices, label="Select API Platform", type="value", elem_classes="api-cards")
    
    # Custom API inputs (visible when "Others" is selected)
    with gr.Group(visible=False) as custom_api_group:
        custom_api_name = gr.Textbox(label="Custom API Name", placeholder="Enter API name (e.g., 'My API')")
        custom_api_format = gr.Radio(choices=["JSON", "YAML"], label="API Format", value="JSON")
    
    # API Base URL input
    with gr.Row():
        api_base_url = gr.Textbox(label="API Specification URL", placeholder="Enter API specification URL")
    
    # Connect API choice to custom API visibility
    api_choice.change(
        fn=update_api_url,
        inputs=[api_choice],
        outputs=[custom_api_group, api_base_url, api_spec_url_state]
    )

    # Update API spec URL state when the text field changes
    def update_api_spec_url_state(url):
        global current_api_spec_url
        print(f"Updating API spec URL state to: {url}")
        # Also update the global variable
        current_api_spec_url = url
        return gr.update(value=url)
    
    api_base_url.change(
        fn=update_api_spec_url_state,
        inputs=[api_base_url],
        outputs=[api_spec_url_state]
    )
    
    # Load API Specification button
    load_btn = gr.Button("Load API Specification", elem_classes="action-btn")
    loading_indicator = gr.HTML("<div class='loading-spinner'></div>", visible=False)
    message_box = gr.HTML("", visible=False)

    # Endpoints section
    with gr.Group(visible=False, elem_classes="endpoints-section") as endpoints_section:
        # Endpoint type selector (GET, POST, or ALL)
        endpoint_type = gr.Radio(
            choices=["GET", "POST", "ALL"], 
            value="GET", 
            label="Endpoints Type", 
            elem_classes="endpoint-type-selector"
        )
        
        # Deselect All checkbox
        with gr.Row():
            deselect_all_cb = gr.Checkbox(label="Deselect All", value=False)
        
        with gr.Row():
            edit_btn = gr.Button("Edit", interactive=False, elem_classes="reset-btn")
            reset_btn = gr.Button("Reset", interactive=False, elem_classes="reset-btn")
        
        # Accordion for endpoint groups
        max_groups = 100  # Reduced for simplicity
        accordion_placeholders = []
        for i in range(max_groups):
            with gr.Accordion(label="", open=False, visible=False, elem_classes="custom-accordion") as acc:
                cb = gr.CheckboxGroup(label="", choices=[], value=[], elem_classes="custom-checkbox")
            accordion_placeholders.append((acc, cb))
        
        continue_btn = gr.Button("Generate Schema", elem_classes="action-btn")

    # Parameters section
    with gr.Group(elem_classes="param-group", visible=False) as param_group:
        param_header = gr.Markdown("### Parameters Required")
        param_components = []
        for i in range(5):
            with gr.Group(visible=False, elem_classes="param-item") as group:
                param_display = gr.Markdown(visible=False)
                param_input = gr.Textbox(label="Parameter Value", visible=False)
                param_components.append((group, param_display, param_input))

    # Results section
    with gr.Group(visible=False, elem_classes="results-section") as results_section:
        gr.Markdown("### Results")
        with gr.Tabs() as result_tabs:
            with gr.TabItem("JSON Schema"):
                json_output = gr.Code(label="JSON Schema", language="json", elem_classes="gr-code")
            with gr.TabItem("XML Schema"):
                xml_output = gr.Textbox(label="XML Schema", lines=20, elem_classes="gr-code")
        download_out = gr.File(label="Download Schema Files (ZIP)", visible=True, interactive=True)

    # Function to load API specification
    def load_api_spec(api_choice_val, base_url, custom_name=None, custom_format=None):
        global current_api_spec_url
        
        yield (
            gr.update(visible=True),  # Show loading indicator
            gr.update(value="", visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            *[gr.update(visible=False, label="", value=[]) for _ in range(max_groups * 2)],
            gr.update(value="")
        )
        # Handle custom API
        if api_choice_val == "Others":
            # Create a custom API choice value if name is provided
            if custom_name:
                api_choice_val = f"{custom_name} ({custom_format})"
            # Make sure we use the base_url directly for "Others" option
            spec_url = base_url
            print(f"Using custom API spec URL: {spec_url}")
        else:
            # Get endpoints and API spec URL for predefined platforms
            _, spec_url = get_endpoints(api_choice_val, None)
            if base_url:  # If user provided a URL, use it instead
                spec_url = base_url
                print(f"Using user-provided API spec URL for {api_choice_val}: {spec_url}")
            else:
                print(f"Using default API spec URL for {api_choice_val}: {spec_url}")
        
        # Store the current API spec URL
        current_api_spec_url = spec_url
        print(f"Setting current_api_spec_url to: {current_api_spec_url}")
        
        # Get endpoints using the determined spec_url
        endpoints, _ = get_endpoints(api_choice_val, spec_url)
        
        if not endpoints:
            yield (
                gr.update(visible=True),
                gr.update(value="<div style='color: red;'>No endpoints found</div>", visible=True),
                gr.update(visible=False),
                gr.update(visible=False),
                *[gr.update(visible=False, label="", value=[]) for _ in range(max_groups * 2)],
                gr.update(value=spec_url)
            )
        
        # Group endpoints by GET method (default)
        groups = group_endpoints(endpoints, api_choice_val, 'get')
        group_keys = list(groups.keys())
        updates = []
        
        for i in range(max_groups):
            if i < len(group_keys):
                group = group_keys[i]
                choices = [f"{ep} | GET - {methods['get'].get('summary', 'No summary')}" for ep, methods in groups[group].items() if 'get' in methods]
                updates.extend([
                    gr.update(label=group, visible=bool(choices), open=False),
                    gr.update(choices=choices, value=choices, visible=bool(choices))
                ])
            else:
                updates.extend([gr.update(visible=False, label=""), gr.update(visible=False, choices=[], value=[])])
        
        yield (
            gr.update(visible=False),
            gr.update(value="<div class='success-message'><i class='fas fa-check-circle'></i> API specification loaded successfully</div>", visible=True),
            gr.update(visible=True),
            gr.update(visible=False),
            *updates,
            gr.update(value=spec_url)
        )

    # Function to update endpoints based on selected type (GET, POST, or ALL)
    def update_endpoint_display(api_choice_val, endpoint_type_val, api_spec_url):
        # Convert endpoint type to lowercase
        endpoint_type_val = endpoint_type_val.lower()
        
        # Get endpoints
        endpoints, _ = get_endpoints(api_choice_val, api_spec_url)
        if not endpoints:
            # Even if no endpoints are found, we should still return the endpoint type state
            # and ensure the endpoints section remains visible
            return [gr.update(visible=False, label="", value=[]) for _ in range(max_groups * 2)] + [gr.update(value=endpoint_type_val)]
        
        # Group endpoints by selected type
        groups = group_endpoints(endpoints, api_choice_val, endpoint_type_val)
        group_keys = list(groups.keys())
        updates = []
        
        for i in range(max_groups):
            if i < len(group_keys):
                group = group_keys[i]
                
                if endpoint_type_val == 'all':
                    # For 'all' type, include both GET and POST endpoints
                    choices = []
                    for ep, methods in groups[group].items():
                        for method_type in ['get', 'post']:
                            if method_type in methods:
                                choices.append(f"{ep} | {method_type.upper()} - {methods[method_type].get('summary', 'No summary')}")
                else:
                    # For specific method types
                    choices = [f"{ep} | {endpoint_type_val.upper()} - {methods[endpoint_type_val].get('summary', 'No summary')}" 
                              for ep, methods in groups[group].items() if endpoint_type_val in methods]
                
                updates.extend([
                    gr.update(label=group, visible=bool(choices), open=False),
                    gr.update(choices=choices, value=choices, visible=bool(choices))
                ])
            else:
                updates.extend([gr.update(visible=False, label=""), gr.update(visible=False, choices=[], value=[])])
        
        return updates + [gr.update(value=endpoint_type_val)]

    # Function to lock selected endpoints and generate schema directly
    def lock_selected_endpoints(*checkbox_values):
        all_selected = [sel for group in checkbox_values if isinstance(group, list) for sel in group]
        if not all_selected:
            return [
                [],
                gr.update(interactive=True),
                gr.update(interactive=False),
                gr.update(interactive=False),
                *[gr.update(interactive=True) for _ in range(max_groups)]
            ]
        
        return [
            all_selected,
            gr.update(interactive=False),
            gr.update(interactive=True),
            gr.update(interactive=True),
            *[gr.update(interactive=False) for _ in range(max_groups)]
        ]

    # Function to unlock selected endpoints
    def unlock_selected_endpoints():
        return [
            gr.update(value=[]),
            gr.update(interactive=True),
            gr.update(interactive=False),
            gr.update(interactive=False),
            *[gr.update(interactive=True) for _ in range(max_groups)]
        ]

    # Function to reset selected endpoints
    def reset_selected_endpoints():
        return [
            gr.update(value=[]),
            gr.update(interactive=True),
            gr.update(interactive=False),
            gr.update(interactive=False),
            *[gr.update(interactive=True, value=[]) for _ in range(max_groups)]
        ]

    # Store the current API spec URL in a global variable
    current_api_spec_url = ""

    # Function to generate schema files
    def generate_schemas(api_choice_val, api_spec_url_value, custom_api_name_value, *checkbox_values):
        global current_api_spec_url
        
        print(f"Generate schemas called with api_choice_val: {api_choice_val}")
        print(f"API spec URL value from state: {api_spec_url_value}")
        print(f"Current API spec URL: {current_api_spec_url}")
        print(f"Custom API name from UI: {custom_api_name_value}")
        
        # Get custom API name if "Others" is selected
        custom_name = None
        if api_choice_val == "Others":
            # Use the custom API name passed as a parameter
            custom_name = custom_api_name_value
            
            # If custom_name is None or empty, use a default name
            if not custom_name or custom_name.strip() == "":
                custom_name = "custom_api"
                print(f"Using default custom API name: {custom_name}")
        
        # Extract both path and method from selected endpoints
        all_selected = []
        for group in checkbox_values:
            if isinstance(group, list):
                for sel in group:
                    # Parse both path and method from the selection
                    parts = sel.split(" | ")
                    if len(parts) >= 2:
                        path = parts[0].strip()
                        method = parts[1].split(" - ")[0].strip().lower()  # Extract GET or POST
                        all_selected.append((path, method))
        
        if not all_selected:
            return (
                gr.update(visible=False),
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value=None)
            )
        
        # Use the current API spec URL that was set when loading the API specification
        api_spec_url = current_api_spec_url
        
        # If we still don't have a URL, try to use the one from the state
        if not api_spec_url:
            api_spec_url = api_spec_url_value
            print(f"Using API spec URL from state: {api_spec_url}")
        
        print(f"API Choice: {api_choice_val}")
        print(f"API Spec URL: {api_spec_url}")
        print(f"Selected endpoints count: {len(all_selected)}")
        
        # Check if api_choice_val is None
        if api_choice_val is None:
            print(f"Error: API choice is None")
            return (
                gr.update(visible=True),
                gr.update(value="Error: Please select an API platform first"),
                gr.update(value="Error: Please select an API platform first"),
                gr.update(value=None)
            )
        
        # Check if api_spec_url is empty
        if not api_spec_url:
            print(f"Error: API spec URL is empty")
            return (
                gr.update(visible=True),
                gr.update(value="Error: API specification URL is empty. Please select a valid API platform or enter a URL."),
                gr.update(value="Error: API specification URL is empty. Please select a valid API platform or enter a URL."),
                gr.update(value=None)
            )
        
        # Generate schema files
        try:
            # Pass the custom API name if it's available
            if api_choice_val == "Others" and custom_name:
                result = generate_schema_files(api_choice_val, all_selected, api_spec_url, custom_name)
            else:
                result = generate_schema_files(api_choice_val, all_selected, api_spec_url)
            
            # Create a temporary file with .zip extension
            fd, temp_path = tempfile.mkstemp(suffix='.zip')
            os.close(fd)
            
            # Write the BytesIO content to the temporary file
            with open(temp_path, 'wb') as f:
                f.write(result["zip"].getvalue())
                
            print(f"Temporary zip file created at: {temp_path}")
            
        except Exception as e:
            print(f"Error generating schema files: {e}")
            return (
                gr.update(visible=True),
                gr.update(value=f"Error generating schema files: {str(e)}"),
                gr.update(value=f"Error generating schema files: {str(e)}"),
                gr.update(value=None)
            )
        
        return (
            gr.update(visible=True),
            gr.update(value=result["json"]),
            gr.update(value=result["xml"]),
            gr.update(value=temp_path)  # Use the temporary file path instead of BytesIO
        )

    # Function to handle API choice change - collapses sections when API is changed
    def handle_api_choice_change(api_choice_val):
        global current_api_spec_url
        # Reset the current API spec URL when changing API choice
        current_api_spec_url = ""
        # First, get the outputs from update_api_url
        custom_api_visibility, api_base_url_value, api_spec_url_value = update_api_url(api_choice_val)
        # Then, add the visibility updates for endpoints and results sections
        return custom_api_visibility, api_base_url_value, api_spec_url_value, gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)
    
    # Update API choice to handle collapsing sections
    api_choice.change(
        fn=handle_api_choice_change,
        inputs=[api_choice],
        outputs=[custom_api_group, api_base_url, api_spec_url_state, endpoints_section, results_section, message_box]
    )
    
    # Connect UI components to functions
    load_btn.click(
        fn=load_api_spec,
        inputs=[api_choice, api_base_url, custom_api_name, custom_api_format],
        outputs=[
            loading_indicator,
            message_box,
            endpoints_section,
            results_section
        ] + [comp for acc, cb in accordion_placeholders for comp in (acc, cb)] + [api_spec_url_state]
    )

    # Function to update endpoints and ensure endpoints section remains visible
    def update_endpoints_and_maintain_visibility(api_choice_val, endpoint_type_val, api_spec_url):
        # Get updates for accordion placeholders and endpoint type state
        updates = update_endpoint_display(api_choice_val, endpoint_type_val, api_spec_url)
        # Return these updates plus an update to keep the endpoints section visible
        return updates + [gr.update(visible=True)]
    
    endpoint_type.change(
        fn=update_endpoints_and_maintain_visibility,
        inputs=[api_choice, endpoint_type, api_spec_url_state],
        outputs=[comp for acc, cb in accordion_placeholders for comp in (acc, cb)] + [endpoint_type_state, endpoints_section]
    )

    
    # Function to handle deselect all checkbox
    def deselect_all_endpoints(deselect_all, *current_values):
        if not deselect_all:
            return [gr.update(value=val) for val in current_values]
        
        # Deselect all checkboxes
        updates = [gr.update(value=[]) for _ in current_values]
        
        return updates
    
    # Connect deselect all checkbox
    
    deselect_all_cb.change(
        fn=deselect_all_endpoints,
        inputs=[deselect_all_cb] + [cb for _, cb in accordion_placeholders],
        outputs=[cb for _, cb in accordion_placeholders]
    )
    
    continue_btn.click(
        fn=lock_selected_endpoints,
        inputs=[cb for _, cb in accordion_placeholders],
        outputs=[
            locked_endpoints_state, 
            continue_btn, 
            edit_btn,
            reset_btn
        ] + [cb for _, cb in accordion_placeholders]
    )

    edit_btn.click(
        fn=unlock_selected_endpoints,
        inputs=[],
        outputs=[
            locked_endpoints_state, 
            continue_btn, 
            edit_btn,
            reset_btn
        ] + [cb for _, cb in accordion_placeholders]
    )

    reset_btn.click(
        fn=reset_selected_endpoints,
        inputs=[],
        outputs=[
            locked_endpoints_state, 
            continue_btn, 
            edit_btn,
            reset_btn
        ] + [cb for _, cb in accordion_placeholders]
    )

    continue_btn.click(
        fn=generate_schemas,
        inputs=[api_choice, api_spec_url_state, custom_api_name] + [cb for _, cb in accordion_placeholders],
        outputs=[
            results_section,
            json_output,
            xml_output,
            download_out
        ]
    )

    # Function to return the zip file for download
    def download_schema_files(json_content, xml_content):
        # Generate schema files in memory
        if not json_content or not xml_content:
            return None
            
        try:
            # Determine API name from JSON content
            meta_data = json.loads(json_content)
            api_name = meta_data.get("name", "schema").lower().replace(" ", "_")
            
            # Create a zip file in memory
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                zip_file.writestr(f"{api_name}_datasource_plugin_meta.json", json_content)
                zip_file.writestr(f"{api_name}_default_schema.orx", xml_content)
            
            zip_buffer.seek(0)
            
            # Create a temporary file with .zip extension
            fd, temp_path = tempfile.mkstemp(suffix='.zip')
            os.close(fd)
            
            # Write the BytesIO content to the temporary file
            with open(temp_path, 'wb') as f:
                f.write(zip_buffer.getvalue())
            
            # Return the file path with a filename for download
            return (temp_path, f"{api_name}_schema_files.zip")
            
        except Exception as e:
            print(f"Error creating download file: {e}")
            return None
    

if __name__ == "__main__":
    demo.launch(show_error=True)
