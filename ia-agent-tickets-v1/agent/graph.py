"""
LangGraph ReAct agent for the IA Agent
Using memory with unique thread_id per conversation
"""
import os
import uuid
from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import InMemorySaver

# Import tools and prompts
from tools import create_tools
from prompts import get_prompt_for_role

# Get environment variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY", os.getenv("OPENAI_API_KEY", ""))
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it:free")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:3001")



def create_agent():
    """Creates and returns the compiled LangGraph agent"""
    
    # Initialize primary LLM
    primary_llm = ChatGroq(
        api_key=GROQ_API_KEY,
        model=LLM_MODEL,
        temperature=0.1
    )
    
    # Create fallback LLM via OpenRouter
    fallback_llm = ChatOpenAI(
        api_key=OPENROUTER_API_KEY or "dummy_key",
        base_url="https://openrouter.ai/api/v1",
        model=OPENROUTER_MODEL,
        temperature=0.1
    )
    
    # Configure fallbacks
    llm = primary_llm.with_fallbacks([fallback_llm])
    
    # Create tools
    tools = create_tools()
    
    # Create checkpointer for memory
    checkpointer = InMemorySaver()
    
    # Create react agent with memory
    agent = create_react_agent(
        model=llm,
        tools=tools,
        checkpointer=checkpointer
    )
    
    return agent


def get_response(graph, messages, thread_id: str, user_id: int, user_rol: str):
    """Invoke the graph and return the response"""
    # Use the provided thread_id (should be consistent per user)
    if not thread_id:
        thread_id = f"user-{user_id}"
    
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 30
    }
    
    # Get role-specific system prompt with user context
    print("Iniciando formateo de prompt...")
    system_prompt = get_prompt_for_role(user_rol, user_id)
    print("Prompt formateado ok.")
    
    # Create input with system message and user message
    input_messages = [SystemMessage(content=system_prompt)] + list(messages)
    
    # Invoke the agent
    print("Invocando al agente (LangGraph)...")
    result = graph.invoke(
        {"messages": input_messages},
        config
    )
    print("Respuesta recibida del agente.")
    
    # Get the last AI message with content
    ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
    if ai_messages:
        last_ai = ai_messages[-1]
        if last_ai.content:
            return last_ai.content
    
    # If no content but there were tool calls, extract results
    last_message = result["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        tool_results = []
        for msg in result["messages"]:
            if hasattr(msg, "type") and msg.type == "tool":
                tool_results.append(msg.content)
        
        if tool_results:
            return " ".join(tool_results)
        return "Procesado. ¿Hay algo más?"
    
    return "No pude procesar tu solicitud. Intenta de nuevo."
