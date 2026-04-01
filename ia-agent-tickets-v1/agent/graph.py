"""
LangGraph ReAct agent for the IA Agent
"""
import os
from typing import TypedDict, Annotated, Literal, Sequence
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END, START, add_messages
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolNode

# Import tools and prompts
from tools import create_tools
from prompts import get_prompt_for_role

# Get environment variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY", os.getenv("OPENAI_API_KEY", ""))
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:3001")

# Define agent state
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_id: int
    user_rol: str

def create_agent():
    """Creates and returns the compiled LangGraph agent using a custom StateGraph for precise role prompt injection"""
    
    # Initialize LLM
    llm = ChatGroq(
        api_key=GROQ_API_KEY,
        model=LLM_MODEL,
        temperature=0.1
    )
    
    # Create tools
    tools = create_tools()
    llm_with_tools = llm.bind_tools(tools)
    
    def llm_node(state: AgentState):
        """Node that calls the LLM with dynamic state-based system prompt"""
        user_rol = state.get("user_rol", "creador")
        user_id = state.get("user_id", 0)
        messages = state["messages"]
        
        # Build prompt and DO NOT save it into state, just pass it to LLM for this turn
        system_prompt = get_prompt_for_role(user_rol, user_id)
        system_prompt += f"\n\nCONTEXTO ACTUAL: Tu user_id es {user_id}. Siempre que uses una herramienta que pida user_id, usa este valor."
        
        full_messages = [SystemMessage(content=system_prompt)] + list(messages)
        return {"messages": [llm_with_tools.invoke(full_messages)]}
        
    def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "__end__"

    builder = StateGraph(AgentState)
    builder.add_node("llm", llm_node)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "llm")
    builder.add_conditional_edges("llm", should_continue)
    builder.add_edge("tools", "llm")
    
    checkpointer = InMemorySaver()
    return builder.compile(checkpointer=checkpointer)

def get_response(graph, messages, thread_id: str, user_id: int, user_rol: str):
    """Invoke the graph and return the response"""
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 50
    }
    
    # Initialize the state purely with the new message and context data
    # (Memory handles adding this new message to history via `add_messages`)
    result = graph.invoke(
        {
            "messages": list(messages),
            "user_id": user_id,
            "user_rol": user_rol
        },
        config
    )
    
    # Get the last AI message
    for message in reversed(result["messages"]):
        if isinstance(message, AIMessage) and message.content:
            return message.content
            
    return "No encontré una respuesta adecuada."
