"""
FastAPI application for Domain-specific Q&A Agent

It reads the env variables from the .env file and uses them to initialize the Q&A agent.
It has a chat endpoint that allows you to chat with the agent.
"""

import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Cookie, Response
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv

from qa_agent import DomainQAAgent

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_int_env(key: str, default: int) -> int:
    """Parse integer from environment variable with fallback"""
    try:
        return int(os.getenv(key, default))
    except ValueError:
        logger.warning(f"Invalid {key}, using default: {default}")
        return default


def get_float_env(key: str, default: float) -> float:
    """Parse float from environment variable with fallback"""
    try:
        return float(os.getenv(key, default))
    except ValueError:
        logger.warning(f"Invalid {key}, using default: {default}")
        return default


def validate_api_keys():
    """Validate required API keys are present"""
    google_api_key = os.getenv("GOOGLE_API_KEY")
    arcade_api_key = os.getenv("ARCADE_API_KEY")

    if not google_api_key or google_api_key == "your_google_api_key_here":
        raise ValueError("GOOGLE_API_KEY environment variable is required")

    if not arcade_api_key or arcade_api_key == "your_arcade_api_key_here":
        raise ValueError(
            "ARCADE_API_KEY environment variable is required for search and web scraping functionality"
        )

    return google_api_key, arcade_api_key


def build_config() -> Dict[str, Any]:
    """Build configuration from environment variables"""
    google_api_key, arcade_api_key = validate_api_keys()

    return {
        "google_api_key": google_api_key,
        "arcade_api_key": arcade_api_key,
        "user_id": os.getenv("USER_ID", "qa_agent@example.com"),
        "max_results": get_int_env("MAX_RESULTS", 10),
        "max_scrape_length": get_int_env("MAX_SCRAPE_LENGTH", 20000),
        "llm_temperature": get_float_env("LLM_TEMPERATURE", 0.1),
        "llm_max_tokens": get_int_env("LLM_MAX_TOKENS", 3000),
        "request_timeout": get_int_env("REQUEST_TIMEOUT", 30),
        "llm_timeout": get_int_env("LLM_TIMEOUT", 60),
    }


def log_config(config: Dict[str, Any]):
    """Pretty print configuration (excluding API keys)"""
    safe_config = {k: v for k, v in config.items() if not k.endswith("_api_key")}
    logger.info("Configuration loaded:")
    for key, value in safe_config.items():
        logger.info(f"  {key}: {value}")


def create_config() -> Dict[str, Any]:
    """Create and validate complete configuration"""
    try:
        config = build_config()
        log_config(config)
        logger.info("Environment validation completed")
        return config
    except Exception as e:
        logger.error(f"Environment validation failed: {str(e)}")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup Q&A agent"""
    try:
        logger.info("Initializing Q&A Agent...")
        config = create_config()
        # Initialize empty session store instead of single agent
        app.state.user_sessions = {}
        app.state.config = config
        logger.info("Session store initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize session store: {str(e)}")
        raise

    yield

    logger.info("Shutting down session store...")
    # Cleanup all agent instances
    if hasattr(app.state, "user_sessions"):
        for session_id in list(app.state.user_sessions.keys()):
            logger.info(f"Cleaning up session {session_id}")
        app.state.user_sessions.clear()


app = FastAPI(
    title="Domain Q&A Agent API",
    description="A Q&A agent that searches specific domains using Tavily and Langchain",
    version="1.0.0",
    lifespan=lifespan,
)


def get_or_create_agent(session_id: str) -> DomainQAAgent:
    """Get existing agent instance or create new one for session"""
    if not hasattr(app.state, "user_sessions"):
        raise HTTPException(status_code=500, detail="Session store not initialized")

    if session_id not in app.state.user_sessions:
        logger.info(f"Creating new agent instance for session {session_id}")
        app.state.user_sessions[session_id] = DomainQAAgent(config=app.state.config)

    return app.state.user_sessions[session_id]


class ChatRequest(BaseModel):
    message: str
    reset_memory: bool = False


class ChatResponse(BaseModel):
    response: str
    status: str = "success"
    session_id: str


@app.get("/health")
async def health_check():
    """Health check with session store status"""
    return {
        "message": "Domain Q&A Agent API is running",
        "status": "healthy",
        "version": "1.0.0",
        "active_sessions": (
            len(app.state.user_sessions) if hasattr(app.state, "user_sessions") else 0
        ),
    }


@app.post("/chat", response_model=ChatResponse, summary="Chat with Q&A Agent")
async def chat(
    request: ChatRequest, response: Response, session_id: str = Cookie(None)
):
    """Process user questions through the Q&A agent"""
    # Generate new session ID if none exists
    if not session_id:
        session_id = str(uuid.uuid4())
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=3600,  # 1 hour session
        )

    logger.info(f"Processing chat request for session {session_id}")

    # Get or create agent instance for this session
    agent = get_or_create_agent(session_id)

    if request.reset_memory:
        agent.reset_memory()
        logger.info(f"Memory reset requested for session {session_id}")

    # Async Call to agent's chat method
    response_text = await agent.achat(request.message)
    logger.info(f"Successfully processed chat request for session {session_id}")

    return ChatResponse(response=response_text, status="success", session_id=session_id)


@app.post("/reset", summary="Reset conversation memory")
async def reset_memory(session_id: str = Cookie(None)):
    """Reset conversation memory for the current session"""
    if not session_id:
        raise HTTPException(status_code=400, detail="No active session")

    agent = get_or_create_agent(session_id)
    agent.reset_memory()
    logger.info(f"Memory reset via endpoint for session {session_id}")
    return {"message": "Conversation memory has been reset", "status": "success"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
