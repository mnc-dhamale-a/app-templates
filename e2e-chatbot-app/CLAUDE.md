# Databricks E2E Streamlit Chatbot Application - Context for Claude

## Project Overview

This is a **production-ready Streamlit-based chatbot application** built specifically for **Databricks environments**. It provides a simple, elegant web interface for interacting with Databricks serving endpoints including ChatModels, Agent Bricks (ChatAgent), and ResponsesAgent endpoints.

**Key characteristics:**

- Pure Python implementation with Streamlit
- Single-file main application (app.py)
- Support for multiple endpoint types with automatic detection
- Streaming responses with real-time UI updates
- Tool call visualization
- Feedback submission support
- Minimal dependencies (MLflow + Streamlit)

## Architecture

### File Structure

```
e2e-chatbot-app/
├── app.py                    # Main Streamlit application
├── messages.py               # Message classes (UserMessage, AssistantResponse)
├── model_serving_utils.py    # Endpoint querying and feedback utilities
├── requirements.txt          # Python dependencies
└── app.yaml                  # Databricks app runtime config
```

### Key Technologies

- **Streamlit 1.44.1** - Web UI framework
- **MLflow 2.21.2+** - Model serving client and type definitions
- **Databricks SDK** - Workspace API access for endpoint metadata

## File Descriptions

### app.py (337 lines)

The main Streamlit application that:

- Detects endpoint type automatically (`chat/completions`, `agent/v2/chat`, or `agent/v1/responses`)
- Maintains chat history in `st.session_state.history`
- Renders user messages and assistant responses with tool calls
- Implements streaming response handlers for each endpoint type:
  - `query_chat_completions_endpoint_and_render()` - Foundation model endpoints
  - `query_chat_agent_endpoint_and_render()` - ChatAgent endpoints (Agent Bricks v2)
  - `query_responses_endpoint_and_render()` - ResponsesAgent endpoints (Agent Bricks v1)
- Handles streaming errors with automatic fallback to non-streaming queries
- Uses `reduce_chat_agent_chunks()` to accumulate streaming deltas

**Important patterns:**
- Message rendering is delegated to `Message.render()` methods
- All history elements are `Message` objects (UserMessage or AssistantResponse)
- Tool calls are accumulated properly with call_id mapping

### messages.py (95 lines)

Contains message classes kept in a separate module to avoid Streamlit rerun issues with `isinstance()` checks.

**Classes:**

- `Message` (ABC) - Base class with `to_input_messages()` and `render()` methods
- `UserMessage` - Wraps user input, converts to `{"role": "user", "content": "..."}` format
- `AssistantResponse` - Wraps assistant messages (can contain multiple messages for tool calls), tracks `trace_id` for feedback

**Key functions:**

- `render_message(msg)` - Renders individual messages with tool call formatting
- `render_assistant_message_feedback(i, trace_id)` - Streamlit fragment for thumbs up/down feedback

### model_serving_utils.py (268 lines)

Utilities for querying Databricks serving endpoints.

**Key functions:**

- `_get_endpoint_task_type(endpoint_name)` - Returns endpoint type (`chat/completions`, `agent/v2/chat`, `agent/v1/responses`)
- `query_endpoint_stream(endpoint_name, messages, return_traces)` - Routes to appropriate streaming handler
- `query_endpoint(endpoint_name, messages, return_traces)` - Non-streaming query returning (messages, trace_id)
- `_convert_to_responses_format(messages)` - Converts chat messages to ResponsesAgent API format
- `submit_feedback(trace_id, is_correct, user_id, comment, endpoint)` - Logs user feedback using MLflow tracing API
- `endpoint_supports_feedback(endpoint_name)` - Returns True (feedback always supported with tracing)

**Important details:**

- Uses `get_deploy_client("databricks")` from MLflow for endpoint queries
- Uses `mlflow.log_feedback()` for logging user feedback to traces
- Uses `AssessmentSource` and `AssessmentSourceType` from MLflow entities for feedback metadata
- Streaming uses `predict_stream()`, non-streaming uses `predict()`
- Extracts `databricks_request_id` from `databricks_output` and uses it as `trace_id` for feedback

### app.yaml

Databricks app runtime configuration:

```yaml
command: ["streamlit", "run", "app.py"]
env:
  - name: STREAMLIT_BROWSER_GATHER_USAGE_STATS
    value: "false"
  - name: "SERVING_ENDPOINT"
    valueFrom: "serving-endpoint"
```

**Important:** The `SERVING_ENDPOINT` environment variable is populated from the Databricks app resource binding named `serving-endpoint` defined in `databricks.yml`.

## Environment Variables

### Required for Local Development

```bash
# Serving endpoint to query
SERVING_ENDPOINT=your-serving-endpoint-name

# Databricks authentication (choose one)
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=dapi...  # Personal access token

# OR use Databricks CLI profile
DATABRICKS_CONFIG_PROFILE=your-profile-name  # Must run `databricks auth login` first
```

### Required for Production (Databricks Apps)

Automatically provided by the platform when deployed with proper resource bindings:

- `SERVING_ENDPOINT` - From `serving-endpoint` resource binding in databricks.yml
- `DATABRICKS_HOST` - Workspace URL
- `DATABRICKS_CLIENT_ID` - Service principal ID
- `DATABRICKS_CLIENT_SECRET` - Service principal secret

## Running the Application

### Local Development

1. Set environment variables in `.env` file or export them:
   ```bash
   export SERVING_ENDPOINT="your-endpoint-name"
   export DATABRICKS_CONFIG_PROFILE="your-profile"
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Authenticate with Databricks CLI:
   ```bash
   databricks auth login --profile your-profile
   ```

4. Run the Streamlit app:
   ```bash
   streamlit run app.py
   ```

The app will be available at http://localhost:8501

### Deployment to Databricks

**Prerequisites:**

1. Create a `databricks.yml` file in the project root (if not present)
2. Define the serving endpoint resource with `CAN_QUERY` permission
3. Ensure the resource is named `serving-endpoint` to match `app.yaml`

**Example databricks.yml:**

```yaml
resources:
  apps:
    e2e_chatbot_app:
      name: e2e-chatbot-app-${bundle.environment}
      description: "Streamlit chatbot application"
      resources:
        - name: serving-endpoint
          description: "Model serving endpoint for the chatbot"
          serving_endpoint:
            name: your-endpoint-name  # TODO: Update this
            permission: CAN_QUERY
```

**IMPORTANT Pre-Deployment Checklist:**

1. **Check `databricks.yml` for TODOs** - Search for TODO comments (especially for `serving_endpoint.name`)
2. **Update serving endpoint name** - Set the actual endpoint name you want to use
3. **Validate bundle** - Run `databricks bundle validate` to check configuration
4. **Deploy** - Run `databricks bundle deploy` to deploy to Databricks

**Deployment commands:**

```bash
# Validate configuration
databricks bundle validate

# Deploy to dev environment (default)
databricks bundle deploy

# Deploy to staging or prod
databricks bundle deploy -t staging
databricks bundle deploy -t prod

# Start the app
databricks bundle run e2e_chatbot_app

# Check deployment status
databricks bundle summary
```

## Endpoint Type Support

This application automatically detects and supports three types of Databricks serving endpoints:

### 1. Foundation Model Endpoints (`chat/completions`)

Standard chat completion endpoints (e.g., DBRX, Llama, custom fine-tuned models).

**Request format:**
```json
{
  "messages": [
    {"role": "user", "content": "Hello"}
  ]
}
```

**Streaming response:** Uses OpenAI-compatible format with `choices[0].delta.content`

### 2. ChatAgent Endpoints (`agent/v2/chat`)

Agent Bricks v2 endpoints that support tool calling.

**Request format:** Same as chat/completions

**Streaming response:** Uses `ChatAgentChunk` format with:
- `chunk.delta` - Message delta with incremental content
- `chunk.delta.tool_calls` - Tool call information
- Message IDs for tracking multiple parallel messages

**Special handling:**
- Messages are buffered by ID in `message_buffers` OrderedDict
- Chunks are accumulated with `reduce_chat_agent_chunks()`
- Tool calls are accumulated by `call_id` to handle streaming arguments

### 3. ResponsesAgent Endpoints (`agent/v1/responses`)

Agent Bricks v1 endpoints using the Responses API format.

**Request format:**
```json
{
  "input": [
    {"type": "message", "role": "user", "content": [{"type": "output_text", "text": "Hello"}]},
    {"type": "function_call", "call_id": "...", "name": "...", "arguments": "..."},
    {"type": "function_call_output", "call_id": "...", "output": "..."}
  ],
  "context": {},
  "stream": true
}
```

**Streaming response:** Uses `ResponsesAgentStreamEvent` with:
- `event.item.type` - Event type (`message`, `function_call`, `function_call_output`)
- All messages accumulated in `all_messages` list for rendering

**Message conversion:**
- `_convert_to_responses_format()` converts chat messages to Responses API format
- Handles tool calls, tool responses, and regular messages
- Generates UUIDs for messages without IDs

## Key Features

### Streaming Response Handling

All three endpoint types support streaming with real-time UI updates:

1. **Initial state:** Shows "_Thinking..._" placeholder
2. **Streaming:** Updates `response_area` with accumulated content
3. **Error fallback:** Automatically retries without streaming on errors
4. **Multiple messages:** Handles tool calls and responses in sequence

### Tool Call Visualization

When an agent uses tools, the app displays:

```
🛠️ Calling **`function_name`** with:
```json
{function arguments}
```

🧰 Tool Response:
{tool result}
```

### Feedback Support

The application uses **MLflow Tracing API** for collecting user feedback following Databricks best practices:

**Feedback collection flow:**
1. User submits thumbs up/down via Streamlit feedback widget
2. Streamlit rating (0/1) is converted to boolean (False/True)
3. `submit_feedback()` is called with the trace_id
4. Feedback is logged as MLflow assessment using `mlflow.log_feedback()`

**Function signature:**
```python
submit_feedback(
    trace_id: str,              # MLflow trace ID from databricks_request_id
    is_correct: bool,           # True for thumbs up, False for thumbs down
    user_id: Optional[str],     # Optional user identifier
    comment: Optional[str],     # Optional free-text comment
    endpoint: Optional[str]     # Optional (backward compatibility)
)
```

**Feedback attributes:**
- `name`: "user_feedback"
- `value`: Boolean (True for thumbs up, False for thumbs down)
- `source`: AssessmentSource with `source_type=HUMAN` and `source_id` (user_id or "e2e-chatbot-app")
- `rationale`: User comment or default description

**Key advantages:**
- Follows FastAPI reference pattern from Databricks documentation
- No need for special "feedback" served entity in endpoint configuration
- Feedback automatically linked to traces for observability
- Compatible with MLflow Tracing UI for viewing feedback alongside traces
- Enables building evaluation datasets from production feedback
- Supports optional user_id for tracking feedback sources
- Extensible with comment/rationale field for detailed feedback

### Chat History Management

- History stored in `st.session_state.history` as list of `Message` objects
- Persists across Streamlit reruns within a session
- Lost on page refresh (ephemeral, no database)
- Converted to input format with `elem.to_input_messages()` before queries

## Code Style Guidelines

### Python Conventions

- Follow PEP 8 style guide
- Use type hints where appropriate (e.g., `list[dict[str, str]]`)
- Docstrings for all major functions
- Logging configured at INFO level

### Streamlit Patterns

- Use `st.session_state` for persistent state across reruns
- Use `st.chat_message()` context manager for message rendering
- Use `st.empty()` for dynamic content updates during streaming
- Use `@st.fragment` for isolated re-rendering (feedback UI)

### Error Handling

- Try streaming first, fall back to non-streaming on errors
- Clear error messages displayed to user
- Endpoint format validation with helpful error messages
- Graceful handling of missing attributes with `getattr()`

## Common Tasks

### Adding Support for a New Endpoint Type

1. Add task type detection in `_get_endpoint_task_type()`
2. Create streaming handler function `query_X_endpoint_and_render()`
3. Create non-streaming handler function `_query_X_endpoint()`
4. Add format conversion if needed (like `_convert_to_responses_format()`)
5. Update `query_endpoint_and_render()` routing logic

### Customizing the UI

- Modify `st.title()` and `st.write()` in app.py:95-97
- Change chat message rendering in `render_message()` in messages.py:62-77
- Customize tool call display formatting in messages.py:72-74

### Adding New Message Types

1. Create new class in `messages.py` inheriting from `Message`
2. Implement `to_input_messages()` method
3. Implement `render()` method
4. Add to `st.session_state.history` where needed

### Debugging Streaming Issues

- Check endpoint task type with `_get_endpoint_task_type()`
- Enable debug logging: `logging.basicConfig(level=logging.DEBUG)`
- Inspect raw chunks in streaming handlers
- Verify message format matches expected structure for endpoint type
- Test non-streaming path separately

## Known Limitations

### No Persistent Storage

- Chat history is stored in Streamlit session state only
- Lost on page refresh or session timeout
- To add persistence, integrate a database (see e2e-chatbot-app-next for reference)

### Single User Session

- No user authentication or multi-user support
- All users share the same endpoint (defined by `SERVING_ENDPOINT` env var)
- For multi-user apps, add authentication and user-specific endpoint routing

### No Message Editing

- Cannot edit previous messages
- Cannot delete individual messages
- To add these features, implement message ID tracking and UI controls

### Limited Multi-Modal Support

- Text-only input and output
- No image, audio, or file upload support
- To add, extend message classes and update rendering logic

## Troubleshooting

### "Unable to determine serving endpoint" error

**Cause:** `SERVING_ENDPOINT` environment variable not set

**Solution:**
- Local: Set `export SERVING_ENDPOINT="your-endpoint-name"`
- Production: Verify `databricks.yml` has proper resource binding named `serving-endpoint`

### "This app can only run against ChatModel, ChatAgent, or ResponsesAgent endpoints"

**Cause:** Endpoint returned unexpected response format

**Solution:**
- Verify endpoint type with `databricks serving endpoints get <name>`
- Check endpoint is deployed and serving
- Ensure endpoint supports chat-based interactions

### Streaming errors or incomplete responses

**Cause:** Network issues, endpoint errors, or malformed chunks

**Solution:**
- App automatically falls back to non-streaming
- Check MLflow logs for detailed error messages
- Verify endpoint health in Databricks UI

### Feedback not appearing or failing to submit

**Cause:** Tracing not enabled or trace_id not being captured

**Solution:**
- Verify `return_trace=True` is set in `databricks_options` (already enabled in code)
- Check that `databricks_request_id` is being returned in endpoint responses
- Ensure MLflow is properly installed with tracing support: `mlflow>=2.21.2`
- Verify network connectivity and permissions for MLflow tracing backend
- Check application logs for feedback submission errors

## File Locations Reference

- `app.py:16-22` - SERVING_ENDPOINT validation and feedback check
- `app.py:26-87` - `reduce_chat_agent_chunks()` function for ChatAgent streaming
- `app.py:105-113` - Main routing logic `query_endpoint_and_render()`
- `app.py:115-157` - ChatCompletions streaming handler
- `app.py:160-217` - ChatAgent streaming handler
- `app.py:220-313` - ResponsesAgent streaming handler
- `messages.py:12-24` - Message base class
- `messages.py:27-40` - UserMessage class
- `messages.py:43-59` - AssistantResponse class (tracks trace_id)
- `messages.py:62-77` - `render_message()` function
- `messages.py:80-100` - Feedback UI fragment with trace_id handling
- `model_serving_utils.py:1-7` - Imports including MLflow tracing (AssessmentSource, AssessmentSourceType, Optional)
- `model_serving_utils.py:116-131` - `query_endpoint()` - Returns (messages, trace_id)
- `model_serving_utils.py:133-170` - `_query_chat_endpoint()` - Extracts trace_id from databricks_request_id
- `model_serving_utils.py:172-251` - `_query_responses_endpoint()` - Extracts trace_id from databricks_request_id
- `model_serving_utils.py:253-314` - `submit_feedback()` - New signature with trace_id, is_correct, user_id, comment
- `model_serving_utils.py:317-332` - `endpoint_supports_feedback()` (always returns True with tracing)

## Additional Resources

- [Databricks Agent Framework Docs](https://docs.databricks.com/aws/en/generative-ai/agent-framework/chat-app)
- [Databricks Apps Documentation](https://docs.databricks.com/aws/en/dev-tools/bundles/apps-tutorial)
- [MLflow Tracing - GenAI Observability](https://docs.databricks.com/aws/en/mlflow3/genai/tracing)
- [Collect User Feedback with MLflow Tracing](https://docs.databricks.com/aws/en/mlflow3/genai/tracing/collect-user-feedback/)
- [Streamlit Documentation](https://docs.streamlit.io/)
- [MLflow Deployment Client](https://mlflow.org/docs/latest/python_api/mlflow.deployments.html)
- [Databricks SDK for Python](https://docs.databricks.com/en/dev-tools/sdk-python.html)

## Comparison with e2e-chatbot-app-next

This Streamlit app is a simpler, more lightweight alternative to the full-stack e2e-chatbot-app-next:

**Streamlit app (e2e-chatbot-app):**
- ✅ Simple Python-only codebase
- ✅ Fast to deploy and iterate
- ✅ ~600 lines of code total
- ✅ No database setup required
- ❌ No persistent chat history
- ❌ No user authentication
- ❌ Limited UI customization

**Next.js app (e2e-chatbot-app-next):**
- ✅ Full-stack TypeScript application
- ✅ PostgreSQL database with persistent history
- ✅ User authentication
- ✅ Highly customizable React UI
- ✅ Multi-user support
- ❌ More complex (~5000+ lines of code)
- ❌ Requires database setup

**When to use each:**
- Use **Streamlit** for quick prototypes, demos, or single-user internal tools
- Use **Next.js** for production apps with multiple users requiring chat history

---

**Note for Claude**: This file is automatically loaded as context. When working on this project, refer to these guidelines for commands, patterns, and conventions. Keep this file updated as the project evolves.
