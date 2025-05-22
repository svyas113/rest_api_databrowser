---
sdk: gradio
---

# API Data Connector and Client

This project contains two main Python scripts:
1.  `app.py`: A Gradio-based web application for selecting API endpoints from a specification and generating schema files (`_datasource_plugin_meta.json` and `_default_schema.orx`).
2.  `dynamic_api_client.py`: A command-line tool to interactively call API endpoints based on an OpenAPI specification.

## `dynamic_api_client.py` - Standalone API Client

This script allows you to dynamically connect to and call APIs defined by an OpenAPI (Swagger) specification.

### Features

*   Parses local or remote OpenAPI (JSON or YAML) specification files.
*   Automatically detects server URLs.
*   Determines API security requirements (API Key, HTTP Basic/Bearer, OAuth2 Client Credentials).
*   Prompts the user for necessary credentials.
*   Lists available API endpoints for user selection.
*   Prompts for required parameters (path, query, header, request body).
*   Makes API calls using the `requests` library.
*   Displays API responses.
*   Includes a fallback minimal parser if `api_schema_generatorV5.py` is not found (for basic functionality).

### Prerequisites

*   Python 3.7+
*   `requests` library (`pip install requests`)
*   `PyYAML` library (`pip install pyyaml`)
*   (Optional but recommended) `api_schema_generatorV5.py` in the same directory or Python path for full parsing capabilities.

### Usage

1.  **Run from the command line:**
    ```bash
    python dynamic_api_client.py <path_or_url_to_api_spec>
    ```
    Replace `<path_or_url_to_api_spec>` with the actual file path or URL to your OpenAPI specification file (e.g., `openapi.json`, `swagger.yaml`, `https://api.example.com/openapi.json`).

2.  **Follow the prompts:**
    *   If the base URL cannot be determined, you'll be asked to enter it.
    *   The script will identify the required authentication method. Enter your credentials when prompted.
    *   A list of available endpoints will be displayed. Enter the numbers of the endpoints you wish to call, separated by commas.
    *   For each selected endpoint, provide values for any required parameters.
    *   The script will then make the API calls and display the responses.

### Example

```bash
python dynamic_api_client.py ./my_api_spec.yaml
```

### Notes

*   **OAuth2 Support:** Currently, only the Client Credentials flow is implemented for OAuth2. The script will attempt to fetch the token automatically.
*   **Parameter Handling:** The script prompts for path, query, and header parameters. For request bodies, it currently supports raw JSON input and URL-encoded form data.
*   **$ref Resolution:**
    *   If `api_schema_generatorV5.py` is available and the spec is a local file, it will be used for more robust parsing, including some `$ref` resolutions within its capabilities.
    *   The built-in minimal parser has limited `$ref` resolution (primarily for top-level components like security schemes). Complex nested `$ref`s, especially within parameters or request bodies, might not be fully resolved by the minimal parser.
*   **Security:** Be cautious when entering sensitive credentials. The script uses `input()` for passwords, which might be visible on screen or in shell history depending on your terminal configuration.

## `app.py` - API Schema Generator UI

This Gradio application provides a user interface to:
*   Load API specifications (Okta, SailPoint IdentityNow, SailPoint IIQ, or custom URLs).
*   Browse and select API endpoints (GET, POST, or ALL).
*   Generate `_datasource_plugin_meta.json` and `_default_schema.orx` files based on selected endpoints.
*   Download the generated files as a ZIP archive.

Refer to the comments and structure within `app.py` for details on its operation with Gradio.

### Running `app.py`

```bash
python app.py
```
This will typically launch a web server, and you can access the UI in your browser (usually at `http://127.0.0.1:7860`).

## Potential Integration of `dynamic_api_client.py` with `app.py`

While `dynamic_api_client.py` is currently a standalone CLI tool, its core logic for parsing API specifications, handling authentication, and making API calls could be integrated into `app.py` or a similar Gradio application to provide a UI for direct API interaction.

Here are some conceptual ideas for integration:

1.  **Add an "API Call" Tab/Section to `app.py`:**
    *   After loading an API specification and selecting endpoints (as `app.py` already does for schema generation), a new section could allow the user to trigger calls to these selected endpoints.
    *   The UI would need to:
        *   Dynamically generate input fields for required authentication details based on the parsed `securitySchemes` (similar to how `dynamic_api_client.py` prompts for them).
        *   For each selected endpoint, dynamically generate input fields for its parameters (path, query, header, body).
        *   A "Call API" button would trigger the request.
        *   Display the API response (status code, headers, body) in the UI.

2.  **Refactor Core Logic into Reusable Functions/Classes:**
    *   The API parsing, authentication handling, parameter collection, and request-making logic from `dynamic_api_client.py` could be refactored into functions or classes within a utility module (e.g., `api_interaction_utils.py`).
    *   Both `dynamic_api_client.py` (for CLI use) and `app.py` (for UI use) could then import and use this shared module. This promotes code reuse and consistency.

3.  **State Management in Gradio:**
    *   Gradio's `gr.State` would be crucial for managing API specification data, authentication credentials (securely, if possible, though browser-based storage has limitations), selected endpoints, and parameter values across interactions.

4.  **Workflow:**
    *   User loads API spec in `app.py`.
    *   `app.py` parses the spec (potentially using `ApiSchemaGeneratorV5` or the refactored utility module).
    *   User navigates to an "API Interaction" or "Test Endpoint" section.
    *   UI prompts for authentication based on the spec.
    *   User selects an endpoint.
    *   UI prompts for parameters for that endpoint.
    *   User clicks "Send Request".
    *   The backend (Gradio event handler) uses the refactored logic to construct and send the API request.
    *   The response is displayed in the UI.

### Challenges and Considerations for Integration:

*   **Security of Credentials:** Handling API keys, passwords, and tokens in a web UI requires careful consideration. Storing them in `gr.State` might be acceptable for local development, but for a deployed application, more secure methods would be needed (e.g., backend secrets management, temporary session storage).
*   **Asynchronous Operations:** API calls can take time. Gradio's handling of long-running operations and providing feedback (loading indicators) would be important.
*   **Complex Request Bodies:** Building a UI to dynamically construct complex JSON or XML request bodies based on a schema can be challenging but powerful.
*   **Error Handling:** Robust error handling and clear feedback to the user in the UI are essential.

This integration would transform `app.py` from just a schema generator into a more comprehensive API development and testing tool.
