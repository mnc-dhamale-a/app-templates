from mlflow.deployments import get_deploy_client
from databricks.sdk import WorkspaceClient
import mlflow
from mlflow.entities import AssessmentSource, AssessmentSourceType
import json
import uuid
from typing import Optional

import logging

logging.basicConfig(
    format="%(levelname)s [%(asctime)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.DEBUG
)

def _get_endpoint_task_type(endpoint_name: str) -> str:
    """Get the task type of a serving endpoint."""
    try:
        w = WorkspaceClient()
        ep = w.serving_endpoints.get(endpoint_name)
        return ep.task if ep.task else "chat/completions"
    except Exception:
        return "chat/completions"

def _convert_to_responses_format(messages):
    """Convert chat messages to ResponsesAgent API format."""
    input_messages = []
    for msg in messages:
        if msg["role"] == "user":
            input_messages.append({"role": "user", "content": msg["content"]})
        elif msg["role"] == "assistant":
            # Handle assistant messages with tool calls
            if msg.get("tool_calls"):
                # Add function calls
                for tool_call in msg["tool_calls"]:
                    input_messages.append({
                        "type": "function_call",
                        "id": tool_call["id"],
                        "call_id": tool_call["id"],
                        "name": tool_call["function"]["name"],
                        "arguments": tool_call["function"]["arguments"]
                    })
                # Add assistant message if it has content
                if msg.get("content"):
                    input_messages.append({
                        "type": "message",
                        "id": msg.get("id", str(uuid.uuid4())),
                        "content": [{"type": "output_text", "text": msg["content"]}],
                        "role": "assistant"
                    })
            else:
                # Regular assistant message
                input_messages.append({
                    "type": "message",
                    "id": msg.get("id", str(uuid.uuid4())),
                    "content": [{"type": "output_text", "text": msg["content"]}],
                    "role": "assistant"
                })
        elif msg["role"] == "tool":
            input_messages.append({
                "type": "function_call_output",
                "call_id": msg.get("tool_call_id"),
                "output": msg["content"]
            })
    return input_messages

def _throw_unexpected_endpoint_format():
    raise Exception("This app can only run against ChatModel, ChatAgent, or ResponsesAgent endpoints")

def query_endpoint_stream(endpoint_name: str, messages: list[dict[str, str]], return_traces: bool):
    task_type = _get_endpoint_task_type(endpoint_name)
    
    if task_type == "agent/v1/responses":
        return _query_responses_endpoint_stream(endpoint_name, messages, return_traces)
    else:
        return _query_chat_endpoint_stream(endpoint_name, messages, return_traces)

def _query_chat_endpoint_stream(endpoint_name: str, messages: list[dict[str, str]], return_traces: bool):
    """Invoke an endpoint that implements either chat completions or ChatAgent and stream the response"""
    client = get_deploy_client("databricks")

    # Prepare input payload
    inputs = {
        "messages": messages,
    }
    if return_traces:
        inputs["databricks_options"] = {"return_trace": True}

    for chunk in client.predict_stream(endpoint=endpoint_name, inputs=inputs):
        if "choices" in chunk:
            yield chunk
        elif "delta" in chunk:
            yield chunk
        else:
            _throw_unexpected_endpoint_format()

def _query_responses_endpoint_stream(endpoint_name: str, messages: list[dict[str, str]], return_traces: bool):
    """Stream responses from agent/v1/responses endpoints using MLflow deployments client."""
    client = get_deploy_client("databricks")
    
    input_messages = _convert_to_responses_format(messages)
    
    # Prepare input payload for ResponsesAgent
    inputs = {
        "input": input_messages,
        "context": {},
        "stream": True
    }
    if return_traces:
        inputs["databricks_options"] = {"return_trace": True}

    for event_data in client.predict_stream(endpoint=endpoint_name, inputs=inputs):
        # Just yield the raw event data, let app.py handle the parsing
        yield event_data

@mlflow.trace
def query_endpoint(endpoint_name, messages, return_traces):
    """
    Query an endpoint, returning the messages and trace ID for feedback.

    This function is wrapped with @mlflow.trace to create a client-side trace.
    The trace_id is extracted from the current active span for feedback logging.

    Returns:
        tuple: (messages list, trace_id string)
    """
    task_type = _get_endpoint_task_type(endpoint_name)

    if task_type == "agent/v1/responses":
        result_messages, _ = _query_responses_endpoint(endpoint_name, messages, return_traces)
    else:
        result_messages, _ = _query_chat_endpoint(endpoint_name, messages, return_traces)

    # Get trace_id from current active span (client-side trace)
    trace_id = mlflow.get_current_active_span().trace_id

    return result_messages, trace_id

def _query_chat_endpoint(endpoint_name, messages, return_traces):
    """
    Calls a model serving endpoint with chat/completions format.

    Returns:
        tuple: (messages list, trace_id string) - trace_id is the databricks_request_id
    """
    inputs = {'messages': messages}
    if return_traces:
        inputs['databricks_options'] = {'return_trace': True}

    res = get_deploy_client('databricks').predict(
        endpoint=endpoint_name,
        inputs=inputs,
    )
    # Extract trace_id from databricks_request_id - this is the MLflow trace ID
    trace_id = res.get("databricks_output", {}).get("databricks_request_id")

    if "messages" in res:
        return res["messages"], trace_id
    elif "choices" in res:
        choice_message = res["choices"][0]["message"]
        choice_content = choice_message.get("content")

        # Case 1: The content is a list of structured objects
        if isinstance(choice_content, list):
            combined_content = "".join([part.get("text", "") for part in choice_content if part.get("type") == "text"])
            reformatted_message = {
                "role": choice_message.get("role"),
                "content": combined_content
            }
            return [reformatted_message], trace_id

        # Case 2: The content is a simple string
        elif isinstance(choice_content, str):
            return [choice_message], trace_id

    _throw_unexpected_endpoint_format()

def _query_responses_endpoint(endpoint_name, messages, return_traces):
    """
    Query agent/v1/responses endpoints using MLflow deployments client.

    Returns:
        tuple: (messages list, trace_id string) - trace_id is the databricks_request_id
    """
    client = get_deploy_client("databricks")

    input_messages = _convert_to_responses_format(messages)

    # Prepare input payload for ResponsesAgent
    inputs = {
        "input": input_messages,
        "context": {}
    }
    if return_traces:
        inputs["databricks_options"] = {"return_trace": True}

    # Make the prediction call
    response = client.predict(endpoint=endpoint_name, inputs=inputs)

    # Extract messages from the response
    result_messages = []
    # Extract trace_id from databricks_request_id - this is the MLflow trace ID
    trace_id = response.get("databricks_output", {}).get("databricks_request_id")
    
    # Process the output items from ResponsesAgent response
    output_items = response.get("output", [])
    
    for item in output_items:
        item_type = item.get("type")
        
        if item_type == "message":
            # Extract text content from message
            text_content = ""
            content_parts = item.get("content", [])
            
            for content_part in content_parts:
                if content_part.get("type") == "output_text":
                    text_content += content_part.get("text", "")
            
            if text_content:
                result_messages.append({
                    "role": "assistant",
                    "content": text_content
                })
                
        elif item_type == "function_call":
            # Handle function calls
            call_id = item.get("call_id")
            function_name = item.get("name")
            arguments = item.get("arguments", "")
            
            tool_calls = [{
                "id": call_id,
                "type": "function", 
                "function": {
                    "name": function_name,
                    "arguments": arguments
                }
            }]
            result_messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": tool_calls
            })
            
        elif item_type == "function_call_output":
            # Handle function call output/result
            call_id = item.get("call_id")
            output_content = item.get("output", "")
            
            result_messages.append({
                "role": "tool",
                "content": output_content,
                "tool_call_id": call_id
            })
    
    return result_messages or [{"role": "assistant", "content": "No response found"}], trace_id

def submit_feedback(
    trace_id: str,
    is_correct: bool,
    user_id: Optional[str] = None,
    comment: Optional[str] = None,
    endpoint: Optional[str] = None
):
    """
    Submit user feedback using MLflow tracing API.

    This follows the Databricks recommended pattern for collecting user feedback
    on GenAI application traces for observability and evaluation.

    Args:
        trace_id: The MLflow trace ID (from databricks_request_id in endpoint responses)
        is_correct: True for thumbs up, False for thumbs down
        user_id: Optional user identifier for tracking feedback source
        comment: Optional free-text comment/rationale from user
        endpoint: Optional endpoint name (kept for backward compatibility, not used)

    Returns:
        The logged feedback assessment from MLflow

    Raises:
        Exception: If feedback logging fails

    Example:
        >>> submit_feedback(
        ...     trace_id="tr-1234567890abcdef",
        ...     is_correct=True,
        ...     user_id="user@example.com"
        ... )
    """
    if trace_id is None:
        logging.warning("No trace_id provided, skipping feedback submission")
        return None

    # Create assessment source to track that this is human feedback
    source = AssessmentSource(
        source_type=AssessmentSourceType.HUMAN,
        source_id=user_id or "e2e-chatbot-app"
    )

    # Generate rationale from comment or default description
    rating_string = "positive" if is_correct else "negative"
    rationale = comment or f"User provided {rating_string} feedback"

    try:
        # Log feedback using MLflow tracing API
        # Reference: https://docs.databricks.com/aws/en/mlflow3/genai/tracing/collect-user-feedback/
        feedback_assessment = mlflow.log_feedback(
            trace_id=trace_id,
            name="user_feedback",
            value=is_correct,
            source=source,
            rationale=rationale
        )
        logging.info(f"Successfully logged feedback for trace {trace_id}: {rating_string}")
        return feedback_assessment
    except Exception as e:
        logging.error(f"Failed to log feedback for trace {trace_id}: {e}")
        raise


def endpoint_supports_feedback(endpoint_name):
    """
    Check if the endpoint supports feedback.

    With MLflow tracing API, feedback is always supported when tracing is enabled.
    This function now always returns True since we enable tracing with return_trace=True.

    The legacy feedback endpoint API required a special "feedback" served entity,
    but the modern MLflow tracing API logs feedback directly to traces.

    Args:
        endpoint_name: The serving endpoint name (kept for backward compatibility)

    Returns:
        True - feedback is always supported with MLflow tracing
    """
    return True
