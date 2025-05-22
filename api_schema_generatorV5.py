import os
import requests
import yaml
import json
import re
import xml.dom.minidom
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, List, Any, Optional, Tuple, Set
from collections import defaultdict

class ApiSchemaGeneratorV5:
    """
    A class to dynamically process API specifications and generate appropriate output files
    like datasource_plugin_meta.json and default_schema.orx files.
    
    Version 5: Added protection against circular references in schema objects
    """
    
    def __init__(self, api_spec_url: str, api_name: str = None, selected_endpoints: List[str] = None):
        """
        Initialize the ApiSchemaGeneratorV5 with an API specification URL.
        
        Args:
            api_spec_url: URL or path to the API specification (OpenAPI/Swagger)
            api_name: Optional name for the API (will be extracted from spec if not provided)
            selected_endpoints: Optional list of endpoint paths to include in the schema
        """
        self.api_spec_url = api_spec_url
        self.api_name = api_name
        self.api_spec = None
        self.api_info = None
        self.auth_info = None
        self.endpoints = None
        self.schema_objects = None
        self.common_parameters = {}  # Store common parameters across endpoints
        self.selected_endpoints = selected_endpoints  # Store selected endpoints
        
    def fetch_api_spec(self) -> dict:
        """Fetch and parse the API specification"""
        try:
            if self.api_spec_url.startswith(('http://', 'https://')):
                response = requests.get(self.api_spec_url)
                response.raise_for_status()
                content = response.text
            else:
                with open(self.api_spec_url, 'r') as f:
                    content = f.read()
            
            # Determine if it's JSON or YAML
            try:
                spec = json.loads(content)
            except json.JSONDecodeError:
                spec = yaml.safe_load(content)
            
            self.api_spec = spec
            return spec
        except Exception as e:
            print(f"Error fetching API specification: {str(e)}")
            return {}
    
    def extract_api_info(self) -> dict:
        """Extract essential information from the API specification"""
        if not self.api_spec:
            self.fetch_api_spec()
        
        if not self.api_spec:
            return {}
        
        api_info = {
            'title': self.api_spec.get('info', {}).get('title', 'Unknown API'),
            'description': self.api_spec.get('info', {}).get('description', ''),
            'version': self.api_spec.get('info', {}).get('version', '1.0.0'),
            'endpoints': {},
            'auth': None,
            'schemas': {}
        }
        
        # Set API name if not provided
        if not self.api_name:
            self.api_name = self._sanitize_name(api_info['title'])
        
        # Extract authentication info if present
        if 'components' in self.api_spec and 'securitySchemes' in self.api_spec['components']:
            api_info['auth'] = self._extract_auth_info(self.api_spec)
        
        # Extract common parameters if present
        if 'components' in self.api_spec and 'parameters' in self.api_spec['components']:
            self.common_parameters = self.api_spec['components']['parameters']
        
        # Extract paths and their parameters
        if 'paths' in self.api_spec:
            for path, methods in self.api_spec['paths'].items():
                # Extract path-level parameters
                path_params = []
                if 'parameters' in methods:
                    path_params = methods['parameters']
                
                api_info['endpoints'][path] = {}
                for method, details in methods.items():
                    if method.lower() in ['get', 'post', 'put', 'delete', 'patch']:
                        # Combine path-level and method-level parameters
                        all_params = path_params.copy() if path_params else []
                        if 'parameters' in details:
                            all_params.extend(details['parameters'])
                        
                        # Process parameters
                        params = []
                        for param in all_params:
                            # Handle parameter references
                            if '$ref' in param:
                                ref = param['$ref']
                                param_name = ref.split('/')[-1]
                                if param_name in self.common_parameters:
                                    param = self.common_parameters[param_name]
                            
                            # Extract parameter schema
                            param_schema = param.get('schema', {})
                            param_type = None
                            
                            # Try to get the type from the schema
                            if param_schema:
                                param_type = param_schema.get('type')
                                
                                # If schema has a reference, resolve it
                                if '$ref' in param_schema:
                                    ref_schema = self._resolve_schema_reference(param_schema['$ref'])
                                    if ref_schema:
                                        param_type = ref_schema.get('type')
                            
                            # Default to string if no type is found
                            if not param_type:
                                param_type = 'string'
                            
                            params.append({
                                'name': param.get('name'),
                                'in': param.get('in'),
                                'required': param.get('required', False),
                                'type': param_type,
                                'enum': param_schema.get('enum'),
                                'description': param.get('description', '')
                            })
                        
                        # Extract requestBody if present
                        request_body_schema = None
                        if 'requestBody' in details:
                            content = details['requestBody'].get('content', {})
                            if 'application/json' in content:
                                request_body_schema = content['application/json'].get('schema')
                        
                        # Extract response schema
                        response_schema = None
                        if 'responses' in details:
                            for status_code, response in details['responses'].items():
                                if status_code.startswith('2'):  # 2xx responses
                                    if 'content' in response:
                                        for content_type, content_details in response['content'].items():
                                            if 'schema' in content_details:
                                                response_schema = content_details['schema']
                                                break
                                    break
                        
                        api_info['endpoints'][path][method] = {
                            'summary': details.get('summary', ''),
                            'description': details.get('description', ''),
                            'operationId': details.get('operationId', ''),
                            'parameters': params,
                            'requestBody': request_body_schema,
                            'responseSchema': response_schema,
                            'security': details.get('security')
                        }
        
        # Extract schema objects
        if 'components' in self.api_spec and 'schemas' in self.api_spec['components']:
            api_info['schemas'] = self.api_spec['components']['schemas']
        
        self.api_info = api_info
        self.auth_info = api_info['auth']
        self.endpoints = api_info['endpoints']
        self.schema_objects = api_info['schemas']
        
        return api_info
    
    def _extract_auth_info(self, spec: dict) -> dict:
        """Extract detailed authentication information from API spec"""
        auth_info = {}
        
        if 'securitySchemes' in spec.get('components', {}):
            for scheme_name, scheme_details in spec['components']['securitySchemes'].items():
                auth_type = scheme_details.get('type')
                
                # Extract common info
                auth_info[scheme_name] = {
                    'type': auth_type,
                    'description': scheme_details.get('description', '')
                }
                
                # Extract type-specific info
                if auth_type == 'apiKey':
                    auth_info[scheme_name].update({
                        'name': scheme_details.get('name'),
                        'in': scheme_details.get('in')  # header, query, or cookie
                    })
                elif auth_type == 'http':
                    auth_info[scheme_name].update({
                        'scheme': scheme_details.get('scheme')  # basic, bearer, etc.
                    })
                elif auth_type == 'oauth2':
                    flows = scheme_details.get('flows', {})
                    auth_info[scheme_name]['flows'] = {}
                    
                    for flow_type, flow_details in flows.items():
                        auth_info[scheme_name]['flows'][flow_type] = {
                            'authorizationUrl': flow_details.get('authorizationUrl'),
                            'tokenUrl': flow_details.get('tokenUrl'),
                            'refreshUrl': flow_details.get('refreshUrl'),
                            'scopes': flow_details.get('scopes', {})
                        }
        
        return auth_info
    
    def _sanitize_name(self, name: str) -> str:
        """Sanitize a name to be used as an identifier"""
        if not name:
            return "api"
        
        # Remove special characters and replace spaces with underscores
        sanitized = re.sub(r'[^a-zA-Z0-9_\s]', '', name)
        sanitized = re.sub(r'\s+', '_', sanitized).lower()
        
        return sanitized
    
    def _extract_server_url(self) -> str:
        """Extract server URL from API specification"""
        if not self.api_spec:
            self.fetch_api_spec()
        
        # Extract server information
        servers = self.api_spec.get('servers', [])
        if servers and 'url' in servers[0]:
            return servers[0]['url']
        
        # Default URL if no servers defined
        return "https://api.example.com"
    
    def _extract_maxretries(self) -> str:
        """Extract maximum retries from API specification"""
        if not self.api_spec:
            self.fetch_api_spec()
        
        # Look for rate limiting information in the API spec
        # Check in extensions
        if 'x-ratelimit-retries' in self.api_spec:
            return str(self.api_spec['x-ratelimit-retries'])
        
        # Check in info section
        if 'info' in self.api_spec and 'x-ratelimit-retries' in self.api_spec['info']:
            return str(self.api_spec['info']['x-ratelimit-retries'])
        
        # Check in components section
        if 'components' in self.api_spec and 'x-ratelimit-retries' in self.api_spec['components']:
            return str(self.api_spec['components']['x-ratelimit-retries'])
        
        # Default value if not found in API spec
        return "3"
    
    def _extract_timeout(self) -> str:
        """Extract timeout from API specification"""
        if not self.api_spec:
            self.fetch_api_spec()
        
        # Look for timeout information in the API spec
        # Check in extensions
        if 'x-timeout' in self.api_spec:
            return str(self.api_spec['x-timeout'])
        
        # Check in info section
        if 'info' in self.api_spec and 'x-timeout' in self.api_spec['info']:
            return str(self.api_spec['info']['x-timeout'])
        
        # Check in components section
        if 'components' in self.api_spec and 'x-timeout' in self.api_spec['components']:
            return str(self.api_spec['components']['x-timeout'])
        
        # Default value if not found in API spec
        return "60"
    
    def _get_auth_meta_fields(self) -> List[Dict[str, Any]]:
        """Generate meta fields for authentication based on the API spec"""
        meta_fields = []
        added_fields = set()  # Track added field names to avoid duplication
        
        # Use the custom API name for all field descriptions
        api_name_title = self.api_name.title()
        
        if not self.auth_info:
            # Default to basic auth if no auth info is found
            meta_fields.extend([
                {
                "name": "url",
                "description": f"{api_name_title} URL",
                "sectionName": "Connection Info",
                "defaultValue": self._extract_server_url(),
                "dataType": "STRING",
                "isRequired": True,
                "regex": ""
                },
                {
                    "name": "username",
                    "description": f"{api_name_title} Username",
                    "sectionName": "Connection Info",
                    "defaultValue": "[username]",
                    "dataType": "STRING",
                    "isRequired": True,
                    "regex": ""
                },
                {
                    "name": "password",
                    "description": f"{api_name_title} Password",
                    "sectionName": "Connection Info",
                    "defaultValue": "[password]",
                    "dataType": "STRING",
                    "isRequired": True,
                    "regex": ""
                }
            ])
            added_fields.update(["url", "username", "password"])
        else:
            # Add URL field
            meta_fields.append({
                "name": "url",
                "description": f"{api_name_title} URL",
                "sectionName": "Connection Info",
                "defaultValue": self._extract_server_url(),
                "dataType": "STRING",
                "isRequired": True,
                "regex": ""
            })
            added_fields.add("url")
            
            # Process each auth scheme
            for scheme_name, scheme_details in self.auth_info.items():
                auth_type = scheme_details.get('type')
                
                if auth_type == 'apiKey' and "apitoken" not in added_fields:
                    meta_fields.append({
                        "name": "apitoken",
                        "description": f"{api_name_title} API Token",
                        "sectionName": "Connection Info",
                        "defaultValue": "[your_api_token]",
                        "dataType": "STRING",
                        "isRequired": True,
                        "regex": ""
                    })
                    added_fields.add("apitoken")
                elif auth_type == 'http':
                    scheme = scheme_details.get('scheme', '').lower()
                    if scheme == 'basic':
                        if "username" not in added_fields:
                            meta_fields.append({
                                "name": "username",
                                "description": f"{api_name_title} Username",
                                "sectionName": "Connection Info",
                                "defaultValue": "[username]",
                                "dataType": "STRING",
                                "isRequired": True,
                                "regex": ""
                            })
                            added_fields.add("username")
                        
                        if "password" not in added_fields:
                            meta_fields.append({
                                "name": "password",
                                "description": f"{api_name_title} Password",
                                "sectionName": "Connection Info",
                                "defaultValue": "[password]",
                                "dataType": "STRING",
                                "isRequired": True,
                                "regex": ""
                            })
                            added_fields.add("password")
                    elif scheme == 'bearer' and "token" not in added_fields:
                        meta_fields.append({
                            "name": "token",
                            "description": f"{api_name_title} Bearer Token",
                            "sectionName": "Connection Info",
                            "defaultValue": "[your_bearer_token]",
                            "dataType": "STRING",
                            "isRequired": True,
                            "regex": ""
                        })
                        added_fields.add("token")
                elif auth_type == 'oauth2':
                    flows = scheme_details.get('flows', {})
                    
                    # Check for client credentials flow
                    if 'clientCredentials' in flows:
                        if "clientId" not in added_fields:
                            meta_fields.append({
                                "name": "clientId",
                                "description": f"{api_name_title} Client ID",
                                "sectionName": "Connection Info",
                                "defaultValue": "[your_client_id]",
                                "dataType": "STRING",
                                "isRequired": True,
                                "regex": ""
                            })
                            added_fields.add("clientId")
                        
                        if "clientSecret" not in added_fields:
                            meta_fields.append({
                                "name": "clientSecret",
                                "description": f"{api_name_title} Client Secret",
                                "sectionName": "Connection Info",
                                "defaultValue": "[your_client_secret]",
                                "dataType": "STRING",
                                "isRequired": True,
                                "regex": ""
                            })
                            added_fields.add("clientSecret")
                        
                        if "tokenUrl" not in added_fields:
                            meta_fields.append({
                                "name": "tokenUrl",
                                "description": f"{api_name_title} Token URL",
                                "sectionName": "Connection Info",
                                "defaultValue": flows['clientCredentials'].get('tokenUrl', ''),
                                "dataType": "STRING",
                                "isRequired": True,
                                "regex": ""
                            })
                            added_fields.add("tokenUrl")
                    # Check for password flow
                    elif 'password' in flows:
                        if "username" not in added_fields:
                            meta_fields.append({
                                "name": "username",
                                "description": f"{api_name_title} Username",
                                "sectionName": "Connection Info",
                                "defaultValue": "[username]",
                                "dataType": "STRING",
                                "isRequired": True,
                                "regex": ""
                            })
                            added_fields.add("username")
                        
                        if "password" not in added_fields:
                            meta_fields.append({
                                "name": "password",
                                "description": f"{api_name_title} Password",
                                "sectionName": "Connection Info",
                                "defaultValue": "[password]",
                                "dataType": "STRING",
                                "isRequired": True,
                                "regex": ""
                            })
                            added_fields.add("password")
                        
                        if "clientId" not in added_fields:
                            meta_fields.append({
                                "name": "clientId",
                                "description": f"{api_name_title} Client ID",
                                "sectionName": "Connection Info",
                                "defaultValue": "[your_client_id]",
                                "dataType": "STRING",
                                "isRequired": True,
                                "regex": ""
                            })
                            added_fields.add("clientId")
                        
                        if "clientSecret" not in added_fields:
                            meta_fields.append({
                                "name": "clientSecret",
                                "description": f"{api_name_title} Client Secret",
                                "sectionName": "Connection Info",
                                "defaultValue": "[your_client_secret]",
                                "dataType": "STRING",
                                "isRequired": True,
                                "regex": ""
                            })
                            added_fields.add("clientSecret")
                        
                        if "tokenUrl" not in added_fields:
                            meta_fields.append({
                                "name": "tokenUrl",
                                "description": f"{api_name_title} Token URL",
                                "sectionName": "Connection Info",
                                "defaultValue": flows['password'].get('tokenUrl', ''),
                                "dataType": "STRING",
                                "isRequired": True,
                                "regex": ""
                            })
                            added_fields.add("tokenUrl")
                    # Check for authorization code flow
                    elif 'authorizationCode' in flows:
                        if "clientId" not in added_fields:
                            meta_fields.append({
                                "name": "clientId",
                                "description": f"{api_name_title} Client ID",
                                "sectionName": "Connection Info",
                                "defaultValue": "[your_client_id]",
                                "dataType": "STRING",
                                "isRequired": True,
                                "regex": ""
                            })
                            added_fields.add("clientId")
                        
                        if "clientSecret" not in added_fields:
                            meta_fields.append({
                                "name": "clientSecret",
                                "description": f"{api_name_title} Client Secret",
                                "sectionName": "Connection Info",
                                "defaultValue": "[your_client_secret]",
                                "dataType": "STRING",
                                "isRequired": True,
                                "regex": ""
                            })
                            added_fields.add("clientSecret")
                        
                        if "authorizationUrl" not in added_fields:
                            meta_fields.append({
                                "name": "authorizationUrl",
                                "description": f"{api_name_title} Authorization URL",
                                "sectionName": "Connection Info",
                                "defaultValue": flows['authorizationCode'].get('authorizationUrl', ''),
                                "dataType": "STRING",
                                "isRequired": True,
                                "regex": ""
                            })
                            added_fields.add("authorizationUrl")
                        
                        if "tokenUrl" not in added_fields:
                            meta_fields.append({
                                "name": "tokenUrl",
                                "description": f"{api_name_title} Token URL",
                                "sectionName": "Connection Info",
                                "defaultValue": flows['authorizationCode'].get('tokenUrl', ''),
                                "dataType": "STRING",
                                "isRequired": True,
                                "regex": ""
                            })
                            added_fields.add("tokenUrl")
        
        # Add request parameters from API spec
        if "maxretries" not in added_fields:
            maxretries_value = self._extract_maxretries()
            meta_fields.append({
                "name": "maxretries",
                "description": "Maximum Request Retries",
                "sectionName": "Request Metering",
                "defaultValue": maxretries_value,
                "dataType": "NUMBER",
                "isRequired": True
            })
        
        if "timeout" not in added_fields:
            timeout_value = self._extract_timeout()
            meta_fields.append({
                "name": "timeout",
                "description": "Request Timeout (seconds)",
                "sectionName": "Request Metering",
                "defaultValue": timeout_value,
                "dataType": "NUMBER",
                "isRequired": True
            })
        
        return meta_fields
    
    def generate_datasource_plugin_meta(self) -> dict:
        """Generate the datasource plugin meta JSON file"""
        if not self.api_info:
            self.extract_api_info()
        
        # Handle case where API info couldn't be extracted
        if not self.api_info:
            self.api_info = {
                'title': 'Unknown API',
                'description': '',
                'version': '1.0.0',
                'endpoints': {},
                'auth': None,
                'schemas': {}
            }
        
        # Use the custom API name for all references in the metadata
        api_name_title = self.api_name.title()
        api_name_lower = self.api_name.lower()
        
        meta_data = {
            "name": api_name_title,
            "description": self.api_info.get('description') or f"{api_name_title} Directory",
            "backendCategory": "custom",
            "userCreated": False,
            "icon": f"/{api_name_lower}.svg",
            "isSchemaExtractable": False,
            "meta": self._get_auth_meta_fields()
        }
        
        return meta_data
    
    def _resolve_schema_reference(self, ref: str) -> dict:
        """Resolve a schema reference to the actual schema definition"""
        if not ref.startswith('#/components/schemas/'):
            return {}
        
        schema_name = ref.split('/')[-1]
        if self.schema_objects and schema_name in self.schema_objects:
            return self.schema_objects[schema_name]
        
        return {}
    
    def _extract_properties_from_schema(self, schema: dict) -> dict:
        """Extract properties from a schema, handling references and composition"""
        if not schema or not isinstance(schema, dict):
            return {}
        
        # Handle direct reference
        if '$ref' in schema:
            return self._extract_properties_from_schema(self._resolve_schema_reference(schema['$ref']))
        
        # Get direct properties
        properties = schema.get('properties', {})
        
        # Handle allOf composition
        if 'allOf' in schema:
            for sub_schema in schema['allOf']:
                sub_properties = self._extract_properties_from_schema(sub_schema)
                properties.update(sub_properties)
        
        # Handle oneOf composition
        if 'oneOf' in schema:
            # For oneOf, we'll take properties from the first schema as a representative
            if schema['oneOf'] and isinstance(schema['oneOf'][0], dict):
                first_schema = schema['oneOf'][0]
                sub_properties = self._extract_properties_from_schema(first_schema)
                properties.update(sub_properties)
        
        # Handle anyOf composition
        if 'anyOf' in schema:
            # For anyOf, we'll take properties from all schemas
            for sub_schema in schema['anyOf']:
                sub_properties = self._extract_properties_from_schema(sub_schema)
                properties.update(sub_properties)
        
        return properties
    
    def _extract_common_parameters(self) -> Dict[str, Dict[str, Any]]:
        """Extract common parameters from the API spec"""
        # Return empty dict as we're not using common parameters anymore
        return {}
    
    def _extract_data_models(self) -> List[Dict[str, Any]]:
        """Extract data models from schema objects that are relevant to selected endpoints"""
        data_models = []
        processed_schemas = set()
        relevant_schemas = set()
        
        if not self.schema_objects:
            return data_models
        
        # First, identify which schemas are referenced by the selected endpoints
        if self.selected_endpoints:
            # Extract endpoints based on selected paths and methods
            selected_paths = {}
            for path, method in self.selected_endpoints:
                if path not in selected_paths:
                    selected_paths[path] = []
                selected_paths[path].append(method.lower())
            
            # Process endpoints to find referenced schemas
            for path, methods in self.endpoints.items():
                if path not in selected_paths:
                    continue
                    
                for method, details in methods.items():
                    if method.lower() not in selected_paths.get(path, []):
                        continue
                    
                    # Check response schema
                    response_schema = details.get('responseSchema')
                    if response_schema:
                        self._collect_referenced_schemas(response_schema, relevant_schemas)
                    
                    # Check request body schema
                    request_body = details.get('requestBody')
                    if request_body:
                        self._collect_referenced_schemas(request_body, relevant_schemas)
                    
                    # Check parameter schemas
                    for param in details.get('parameters', []):
                        param_schema = param.get('schema', {})
                        if param_schema:
                            self._collect_referenced_schemas(param_schema, relevant_schemas)
        else:
            # If no endpoints are selected, include all schemas
            relevant_schemas = set(self.schema_objects.keys())
        
        # Process only the relevant schema objects
        for schema_name in relevant_schemas:
            if schema_name in processed_schemas:
                continue
                
            schema_def = self.schema_objects.get(schema_name)
            if not schema_def:
                continue
            
            # Skip non-object schemas
            if schema_def.get('type') and schema_def.get('type') != 'object':
                continue
            
            table = self._create_table_from_schema(schema_name, schema_def)
            if table:
                # Add source information to the table
                table["Source"] = "Components/Schemas"
                table["Type"] = "DATA_MODEL"
                data_models.append(table)
                processed_schemas.add(schema_name)
        
        return data_models
    
    def _collect_referenced_schemas(self, schema: dict, referenced_schemas: set, visited_refs: set = None) -> None:
        """
        Recursively collect all schema references from a schema object.
        
        Args:
            schema: The schema object to process
            referenced_schemas: Set to collect referenced schema names
            visited_refs: Set to track already visited references to prevent circular reference issues
        """
        if not schema or not isinstance(schema, dict):
            return
        
        # Initialize visited_refs if not provided
        if visited_refs is None:
            visited_refs = set()
        
        # Handle direct reference
        if '$ref' in schema:
            ref = schema['$ref']
            if ref.startswith('#/components/schemas/'):
                schema_name = ref.split('/')[-1]
                
                # Skip if we've already processed this reference to avoid circular references
                if ref in visited_refs:
                    return
                
                # Add to referenced schemas and mark as visited
                referenced_schemas.add(schema_name)
                visited_refs.add(ref)
                
                # Recursively collect references from the referenced schema
                if self.schema_objects and schema_name in self.schema_objects:
                    self._collect_referenced_schemas(self.schema_objects[schema_name], referenced_schemas, visited_refs)
        
        # Handle array items
        if schema.get('type') == 'array' and 'items' in schema:
            self._collect_referenced_schemas(schema['items'], referenced_schemas, visited_refs)
        
        # Handle object properties
        if schema.get('type') == 'object' and 'properties' in schema:
            for prop_name, prop_def in schema['properties'].items():
                self._collect_referenced_schemas(prop_def, referenced_schemas, visited_refs)
        
        # Handle composition schemas
        for comp_key in ['allOf', 'oneOf', 'anyOf']:
            if comp_key in schema:
                for sub_schema in schema[comp_key]:
                    self._collect_referenced_schemas(sub_schema, referenced_schemas, visited_refs)
    
    def _extract_endpoints(self) -> List[Dict[str, Any]]:
        """Extract endpoint information"""
        endpoints = []
        
        # Extract common parameters
        common_params = self._extract_common_parameters()

        selected_paths = {}
        if self.selected_endpoints:
            for path, method in self.selected_endpoints:
                if path not in selected_paths:
                    selected_paths[path] = []
                selected_paths[path].append(method.lower())
        
        # Process endpoints
        for path, methods in self.endpoints.items():
            # Skip endpoints that are not in the selected_endpoints list if it's provided
            if self.selected_endpoints is not None and path not in selected_paths:
                continue
            for method, details in methods.items():
                # Skip methods that are not in the selected methods for this path
                if self.selected_endpoints is not None and method.lower() not in selected_paths.get(path, []):
                    continue
                if method.lower() in ['get', 'post', 'put', 'delete', 'patch']:
                    endpoint = {
                        "ID": self._sanitize_name(f"{method}_{path}"),
                        "Name": details.get('operationId') or f"{method.upper()} {path}",
                        "Path": path,
                        "Method": method.upper(),
                        "Summary": details.get('summary', ''),
                        "Description": details.get('description', ''),
                        "Parameters": [],
                        "Type": "ENDPOINT"
                    }
                    
                    # Process parameters
                    for param in details.get('parameters', []):
                        param_key = f"{param.get('name')}:{param.get('in')}"
                        
                        # Extract parameter schema and type
                        param_schema = param.get('schema', {})
                        param_type = None
                        
                        # Try to get the type from the schema
                        if param_schema:
                            param_type = param_schema.get('type')
                            
                            # If schema has a reference, resolve it
                            if '$ref' in param_schema:
                                ref_schema = self._resolve_schema_reference(param_schema['$ref'])
                                if ref_schema:
                                    param_type = ref_schema.get('type')
                        
                        # Default to string if no type is found
                        if not param_type:
                            param_type = 'string'
                        
                        # Check if this is a common parameter
                        if param_key in common_params:
                            endpoint["Parameters"].append({
                                "Name": param.get('name'),
                                "In": param.get('in'),
                                "Required": param.get('required', False),
                                "Type": param_type,  # Include type even for common parameters
                                "IsCommon": True,
                                "CommonRef": param_key
                            })
                        else:
                            endpoint["Parameters"].append({
                                "Name": param.get('name'),
                                "In": param.get('in'),
                                "Required": param.get('required', False),
                                "Type": param_type,
                                "Enum": param_schema.get('enum'),
                                "Description": param.get('description', ''),
                                "IsCommon": False
                            })
                    
                    # Process response schema
                    response_schema = details.get('responseSchema')
                    if response_schema:
                        if '$ref' in response_schema:
                            ref = response_schema['$ref']
                            schema_name = ref.split('/')[-1]
                            endpoint["ResponseModel"] = schema_name
                            endpoint["ResponseType"] = "object"
                        elif response_schema.get('type') == 'array' and 'items' in response_schema:
                            items = response_schema['items']
                            if '$ref' in items:
                                ref = items['$ref']
                                schema_name = ref.split('/')[-1]
                                endpoint["ResponseModel"] = schema_name
                                endpoint["ResponseType"] = "array"
                            else:
                                # Inline schema
                                endpoint["ResponseType"] = "array"
                                endpoint["ResponseInlineSchema"] = items
                        else:
                            # Inline schema
                            endpoint["ResponseType"] = response_schema.get('type', 'object')
                            endpoint["ResponseInlineSchema"] = response_schema
                    
                    # Process request body
                    request_body = details.get('requestBody')
                    if request_body:
                        if '$ref' in request_body:
                            ref = request_body['$ref']
                            schema_name = ref.split('/')[-1]
                            endpoint["RequestModel"] = schema_name
                        else:
                            # Inline schema
                            endpoint["RequestInlineSchema"] = request_body
                    
                    endpoints.append(endpoint)
        
        return endpoints
    
    def _create_table_from_schema(self, schema_name: str, schema_def: dict) -> Optional[Dict[str, Any]]:
        """Create a table definition from a schema object"""
        if not schema_def or not isinstance(schema_def, dict):
            return None
        
        # Extract properties, handling references and composition
        properties = self._extract_properties_from_schema(schema_def)
        
        if not properties:
            return None
        
        # Get required properties
        required = schema_def.get('required', [])
        
        # Create table
        table = {
            "ID": self._sanitize_name(schema_name),
            "Name": schema_name,
            "Description": schema_def.get('description', ''),
            "Properties": []
        }
        
        # Add properties
        for prop_name, prop_def in properties.items():
            property_info = {
                "Name": prop_name,
                "Required": prop_name in required,
                "Description": prop_def.get('description', '') if isinstance(prop_def, dict) else ''
            }
            
            # Determine property type
            if isinstance(prop_def, dict):
                prop_type = prop_def.get('type')
                if prop_type:
                    property_info["Type"] = prop_type
                    
                    # Handle enum values
                    if 'enum' in prop_def:
                        property_info["Enum"] = prop_def['enum']
                    
                    # Handle array items
                    if prop_type == 'array' and 'items' in prop_def:
                        items = prop_def['items']
                        if '$ref' in items:
                            ref = items['$ref']
                            schema_name = ref.split('/')[-1]
                            property_info["ItemsType"] = "reference"
                            property_info["ItemsRef"] = schema_name
                        else:
                            property_info["ItemsType"] = items.get('type', 'object')
                    
                    # Handle object properties
                    if prop_type == 'object' and 'properties' in prop_def:
                        property_info["ObjectProperties"] = []
                        for sub_prop_name, sub_prop_def in prop_def['properties'].items():
                            sub_prop_info = {
                                "Name": sub_prop_name,
                                "Type": sub_prop_def.get('type', 'string'),
                                "Description": sub_prop_def.get('description', '')
                            }
                            property_info["ObjectProperties"].append(sub_prop_info)
                
                # Handle references
                if '$ref' in prop_def:
                    ref = prop_def['$ref']
                    schema_name = ref.split('/')[-1]
                    property_info["Type"] = "reference"
                    property_info["Ref"] = schema_name
            
            table["Properties"].append(property_info)
        
        return table
    
    def _generate_datasource_value(self) -> str:
        """Generate a DataSource value based on API spec information"""
        # Extract server information
        servers = self.api_spec.get('servers', [])
        server_url = "https://api.example.com"
        if servers and 'url' in servers[0]:
            server_url = servers[0]['url']
        
        # Extract authentication information
        auth_info = {}
        if self.auth_info:
            for scheme_name, scheme_details in self.auth_info.items():
                auth_type = scheme_details.get('type')
                
                if auth_type == 'apiKey':
                    auth_info['type'] = 'apiKey'
                    auth_info['name'] = scheme_details.get('name', '')
                    auth_info['in'] = scheme_details.get('in', 'header')
                elif auth_type == 'http':
                    scheme = scheme_details.get('scheme', '').lower()
                    auth_info['type'] = 'http'
                    auth_info['scheme'] = scheme
                elif auth_type == 'oauth2':
                    auth_info['type'] = 'oauth2'
                    flows = scheme_details.get('flows', {})
                    if 'clientCredentials' in flows:
                        auth_info['flow'] = 'clientCredentials'
                        auth_info['tokenUrl'] = flows['clientCredentials'].get('tokenUrl', '')
                    elif 'password' in flows:
                        auth_info['flow'] = 'password'
                        auth_info['tokenUrl'] = flows['password'].get('tokenUrl', '')
                    elif 'authorizationCode' in flows:
                        auth_info['flow'] = 'authorizationCode'
                        auth_info['authorizationUrl'] = flows['authorizationCode'].get('authorizationUrl', '')
                        auth_info['tokenUrl'] = flows['authorizationCode'].get('tokenUrl', '')
        
        # Create a connection string based on the extracted information
        connection_parts = []
        connection_parts.append(f"url={server_url}")
        
        if auth_info:
            connection_parts.append(f"auth_type={auth_info.get('type', 'none')}")
            
            if auth_info.get('type') == 'apiKey':
                connection_parts.append(f"api_key_name={auth_info.get('name', '')}")
                connection_parts.append(f"api_key_in={auth_info.get('in', '')}")
            elif auth_info.get('type') == 'http':
                connection_parts.append(f"http_scheme={auth_info.get('scheme', '')}")
            elif auth_info.get('type') == 'oauth2':
                connection_parts.append(f"oauth2_flow={auth_info.get('flow', '')}")
                if 'tokenUrl' in auth_info:
                    connection_parts.append(f"token_url={auth_info.get('tokenUrl', '')}")
                if 'authorizationUrl' in auth_info:
                    connection_parts.append(f"authorization_url={auth_info.get('authorizationUrl', '')}")
        
        # Add API name and version
        if self.api_info:
            connection_parts.append(f"api_name={self.api_name}")
            connection_parts.append(f"api_version={self.api_info.get('version', '1.0.0')}")
        
        # Create the connection string
        connection_string = ";".join(connection_parts)
        
        # Simulate AES encryption with a prefix
        # In a real implementation, this would be properly encrypted
        return f"{{AES}}{connection_string}"
    
    def generate_default_schema(self) -> str:
        """Generate the default schema XML file"""
        if not self.api_info:
            self.extract_api_info()
        
        # Create XML structure
        root = ET.Element("Xml")
        org = ET.SubElement(root, "ORG", Name=self.api_name.lower())
        
        ET.SubElement(org, "AccessMethod").text = "PDM"
        
        pdm = ET.SubElement(org, "PDM")
        ET.SubElement(pdm, "Name").text = self.api_name.lower()
        
        # Generate DataSource value from API spec information
        datasource_value = self._generate_datasource_value()
        ET.SubElement(pdm, "DataSource").text = datasource_value
        ET.SubElement(pdm, "DataSourceType").text = "XML"
        
        # Add tables
        tables = ET.SubElement(pdm, "Tables")
        
        # We no longer include common parameters section
        
        # Extract data models
        data_models = self._extract_data_models()
        
        # Add a section for data models
        if data_models:
            tables.append(ET.Comment(" DATA MODELS "))
            for model in data_models:
                model_class = ET.SubElement(tables, "Class", type=model["ID"])
                ET.SubElement(model_class, "Name").text = model["Name"]
                ET.SubElement(model_class, "Type").text = "DATA_MODEL"
                ET.SubElement(model_class, "Description").text = model.get("Description", "")
                
                properties = ET.SubElement(model_class, "Properties")
                for prop in model.get("Properties", []):
                    prop_elem = ET.SubElement(properties, "Property", ID=self._sanitize_name(prop["Name"]))
                    ET.SubElement(prop_elem, "Name").text = prop["Name"]
                    ET.SubElement(prop_elem, "Type").text = prop.get("Type", "string")
                    ET.SubElement(prop_elem, "Required").text = str(prop.get("Required", False)).lower()
                    ET.SubElement(prop_elem, "Description").text = prop.get("Description", "")
                    
                    # Handle references
                    if "Ref" in prop:
                        ET.SubElement(prop_elem, "ClassType").text = prop["Ref"]
                    
                    # Handle arrays
                    if prop.get("Type") == "array" and "ItemsType" in prop:
                        items = ET.SubElement(prop_elem, "Items")
                        ET.SubElement(items, "Type").text = prop["ItemsType"]
                        if "ItemsRef" in prop:
                            ET.SubElement(items, "ClassType").text = prop["ItemsRef"]
                    
                    # Handle object properties
                    if prop.get("Type") == "object" and "ObjectProperties" in prop:
                        obj_props = ET.SubElement(prop_elem, "ObjectProperties")
                        for obj_prop in prop["ObjectProperties"]:
                            obj_prop_elem = ET.SubElement(obj_props, "Property", ID=self._sanitize_name(obj_prop["Name"]))
                            ET.SubElement(obj_prop_elem, "Name").text = obj_prop["Name"]
                            ET.SubElement(obj_prop_elem, "Type").text = obj_prop.get("Type", "string")
                            ET.SubElement(obj_prop_elem, "Description").text = obj_prop.get("Description", "")
        
        # Extract endpoints
        endpoints_list = self._extract_endpoints()
        
        # Add a section for endpoints
        if endpoints_list:
            tables.append(ET.Comment(" API ENDPOINTS "))
            for endpoint in endpoints_list:
                endpoint_elem = ET.SubElement(tables, "Endpoint", ID=endpoint["ID"])
                ET.SubElement(endpoint_elem, "Name").text = endpoint["Name"]
                ET.SubElement(endpoint_elem, "Type").text = "ENDPOINT"
                ET.SubElement(endpoint_elem, "Path").text = endpoint["Path"]
                ET.SubElement(endpoint_elem, "Method").text = endpoint["Method"]
                ET.SubElement(endpoint_elem, "Summary").text = endpoint.get("Summary", "")
                ET.SubElement(endpoint_elem, "Description").text = endpoint.get("Description", "")
                
                # Add parameters
                if endpoint.get("Parameters"):
                    params = ET.SubElement(endpoint_elem, "Parameters")
                    for param in endpoint["Parameters"]:
                        param_elem = ET.SubElement(params, "Parameter", ID=self._sanitize_name(param["Name"]))
                        ET.SubElement(param_elem, "Name").text = param["Name"]
                        ET.SubElement(param_elem, "In").text = param["In"]
                        ET.SubElement(param_elem, "Required").text = str(param.get("Required", False)).lower()
                        
                        # Always include Type for all parameters
                        ET.SubElement(param_elem, "Type").text = param.get("Type", "string")
                        
                        # Handle common parameters
                        if param.get("IsCommon", False):
                            ET.SubElement(param_elem, "IsCommon").text = "true"
                            ET.SubElement(param_elem, "CommonRef").text = param["CommonRef"]
                        else:
                            ET.SubElement(param_elem, "IsCommon").text = "false"
                            ET.SubElement(param_elem, "Description").text = param.get("Description", "")
                
                # Add response information
                if "ResponseModel" in endpoint:
                    response = ET.SubElement(endpoint_elem, "Response")
                    ET.SubElement(response, "Type").text = endpoint.get("ResponseType", "object")
                    ET.SubElement(response, "ClassType").text = endpoint["ResponseModel"]
                elif "ResponseInlineSchema" in endpoint:
                    response = ET.SubElement(endpoint_elem, "Response")
                    ET.SubElement(response, "Type").text = endpoint.get("ResponseType", "object")
                    ET.SubElement(response, "InlineSchema").text = json.dumps(endpoint["ResponseInlineSchema"])
                
                # Add request body information
                if "RequestModel" in endpoint:
                    request = ET.SubElement(endpoint_elem, "Request")
                    ET.SubElement(request, "ClassType").text = endpoint["RequestModel"]
                elif "RequestInlineSchema" in endpoint:
                    request = ET.SubElement(endpoint_elem, "Request")
                    ET.SubElement(request, "InlineSchema").text = json.dumps(endpoint["RequestInlineSchema"])
        
        # Convert to pretty XML string
        rough_string = ET.tostring(root, 'utf-8')
        reparsed = xml.dom.minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="    ")
    
    def save_datasource_plugin_meta(self, output_path: str) -> None:
        """Save the datasource plugin meta JSON file"""
        meta_data = self.generate_datasource_plugin_meta()
        
        with open(output_path, 'w') as f:
            json.dump(meta_data, f, indent=2)
        
        print(f"Datasource plugin meta saved to: {output_path}")
    
    def save_default_schema(self, output_path: str) -> None:
        """Save the default schema XML file"""
        schema_xml = self.generate_default_schema()
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(schema_xml)
        
        print(f"Default schema saved to: {output_path}")
    
    def generate_files(self, output_dir: str = None) -> Tuple[str, str]:
        """Generate both the datasource plugin meta JSON and default schema XML files.
        
        Args:
            output_dir: Optional directory to save the files (defaults to current directory)
            
        Returns:
            Tuple of (meta_json_path, schema_xml_path)
        """
        if not self.api_info:
            self.extract_api_info()
        
        # Set default output directory if not provided
        if not output_dir:
            output_dir = os.getcwd()
        else:
            # Create directory if it doesn't exist
            os.makedirs(output_dir, exist_ok=True)
        
        # Generate filenames
        meta_filename = f"{self.api_name.lower()}_datasource_plugin_meta.json"
        schema_filename = f"{self.api_name.lower()}_default_schema.orx"
        
        meta_path = os.path.join(output_dir, meta_filename)
        schema_path = os.path.join(output_dir, schema_filename)
        
        # Save files
        self.save_datasource_plugin_meta(meta_path)
        self.save_default_schema(schema_path)
        
        return (meta_path, schema_path)
