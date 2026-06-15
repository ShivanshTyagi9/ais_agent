"""
OpenAI function-calling agent loop.
Handles multi-turn tool calling with the vessel intelligence tools.
"""

import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from tools.vessel_tools import TOOL_DISPATCH
from tools.tool_schemas import TOOL_SCHEMAS
from agent.system_prompt import get_system_prompt

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

MODEL = "gpt-5-nano"
MAX_TOOL_ROUNDS = 10  # safety limit on tool-calling rounds


def run_agent(user_message: str, conversation_history: list = None) -> dict:
    """
    Run the agent with a user message.

    Args:
        user_message: The user's question or command.
        conversation_history: Optional existing message history for multi-turn.

    Returns:
        dict with:
            - "response": The agent's final text response
            - "messages": Updated conversation history
            - "map_files": List of any generated map file paths
    """
    if conversation_history is None:
        conversation_history = [
            {"role": "system", "content": get_system_prompt()}
        ]

    conversation_history.append({"role": "user", "content": user_message})

    map_files = []
    rounds = 0

    while rounds < MAX_TOOL_ROUNDS:
        rounds += 1

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=conversation_history,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                # temperature=0.1,
            )
        except Exception as e:
            error_msg = f"OpenAI API error: {str(e)}"
            return {
                "response": error_msg,
                "messages": conversation_history,
                "map_files": map_files
            }

        msg = response.choices[0].message

        # Build the message dict to append
        msg_dict = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in msg.tool_calls
            ]

        conversation_history.append(msg_dict)

        # If no tool calls, we have the final answer
        if not msg.tool_calls:
            return {
                "response": msg.content or "",
                "messages": conversation_history,
                "map_files": map_files
            }

        # Execute each tool call
        for tool_call in msg.tool_calls:
            func_name = tool_call.function.name
            try:
                func_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                func_args = {}

            # Dispatch to the tool function
            if func_name in TOOL_DISPATCH:
                try:
                    result = TOOL_DISPATCH[func_name](**func_args)

                    # Track any generated map files
                    if func_name == "visualize_path" and isinstance(result, dict):
                        if "map_file" in result:
                            map_files.append(result["map_file"])

                except Exception as e:
                    result = {"error": f"Tool execution error: {str(e)}"}
            else:
                result = {"error": f"Unknown tool: {func_name}"}

            # Truncate large results for the LLM context
            result_str = json.dumps(result, default=str)
            if len(result_str) > 15000:
                # Keep summary, truncate track data
                if isinstance(result, dict) and 'track' in result:
                    truncated = {k: v for k, v in result.items() if k != 'track'}
                    truncated['track'] = result['track'][:20]
                    truncated['track_truncated'] = True
                    truncated['note'] = (
                        f"Track truncated for context. Full track has "
                        f"{len(result['track'])} points. Use visualize_path "
                        f"to see the complete track on a map."
                    )
                    result_str = json.dumps(truncated, default=str)

            conversation_history.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result_str
            })

    # If we hit the round limit
    return {
        "response": "I reached the maximum number of tool-calling rounds. "
                     "Please try a more specific question.",
        "messages": conversation_history,
        "map_files": map_files
    }
