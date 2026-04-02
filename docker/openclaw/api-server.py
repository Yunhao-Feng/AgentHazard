#!/usr/bin/env python3
"""
OpenClaw API Server
Provides REST API for interacting with OpenClaw sessions
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import subprocess
import json
import os
import glob
import asyncio
from typing import Optional, List, Dict
from datetime import datetime
import aiofiles
import logging
import random
from functools import wraps

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="OpenClaw API Server")

# Configuration
OPENCLAW_HOME = "/root/.openclaw"
SESSIONS_DIR = f"{OPENCLAW_HOME}/agents/main/sessions"
GATEWAY_URL = "http://localhost:18789"

# In-memory session tracking
active_sessions: Dict[str, dict] = {}


def async_retry(max_attempts=3, base_delay=1.0, max_delay=10.0, backoff_factor=2.0, jitter=True, exceptions=(Exception,)):
    """
    通用异步 retry 装饰器
    
    Args:
        max_attempts: 最大尝试次数
        base_delay: 初始等待时间（秒）
        max_delay: 最大等待时间
        backoff_factor: 指数退避系数
        jitter: 是否加随机抖动
        exceptions: 哪些异常触发重试，默认所有异常
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        logger.error(f"[Retry] {func.__name__} failed after {max_attempts} attempts: {e}")
                        raise

                    delay = min(base_delay * (backoff_factor ** (attempt - 1)), max_delay)
                    if jitter:
                        delay *= (0.5 + random.random())

                    logger.warning(f"[Retry] {func.__name__} attempt {attempt}/{max_attempts} failed: {e}, retrying in {delay:.2f}s...")
                    await asyncio.sleep(delay)

        return wrapper
    return decorator

class PromptRequest(BaseModel):
    session_id: Optional[str] = None
    prompt: str
    create_new_session: bool = False


class SessionResponse(BaseModel):
    session_id: str
    response: str
    status: str


class SessionInfo(BaseModel):
    session_id: str
    created_at: Optional[str]
    updated_at: Optional[str]
    file_path: str
    message_count: int


def generate_session_id():
    """Generate a unique session ID"""
    import uuid
    return str(uuid.uuid4())


def get_session_file_path(session_id: str) -> str:
    """Get the file path for a session"""
    return os.path.join(SESSIONS_DIR, f"{session_id}.jsonl")


def get_all_session_files() -> List[str]:
    """Get all session JSONL files"""
    pattern = os.path.join(SESSIONS_DIR, "*.jsonl")
    files = glob.glob(pattern)
    # Exclude sessions.json if present
    return [f for f in files if not f.endswith("sessions.json")]

@async_retry(max_attempts=3, base_delay=0.2, exceptions=(IOError, OSError))
async def read_session_metadata(session_id: str) -> Optional[Dict]:
    """Read session metadata from sessions.json"""
    sessions_json_path = os.path.join(SESSIONS_DIR, "sessions.json")

    if not os.path.exists(sessions_json_path):
        return None

    try:
        async with aiofiles.open(sessions_json_path, 'r') as f:
            content = await f.read()
            sessions_data = json.loads(content)

            # Find session by ID
            for key, session in sessions_data.items():
                if session.get('sessionId') == session_id or key == session_id:
                    return session
    except Exception as e:
        print(f"Error reading session metadata: {e}")

    return None

@async_retry(max_attempts=3, base_delay=0.2, exceptions=(IOError, OSError))
async def count_session_messages(session_file: str) -> int:
    """Count messages in a session JSONL file"""
    if not os.path.exists(session_file):
        return 0

    try:
        count = 0
        async with aiofiles.open(session_file, 'r') as f:
            async for line in f:
                if line.strip():
                    count += 1
        return count
    except Exception:
        return 0

@async_retry(max_attempts=5, base_delay=1.0, exceptions=(Exception,))
async def send_prompt_to_openclaw(session_id: str, prompt: str) -> Dict:
    """Send a prompt to OpenClaw via CLI"""
    try:
        # Build command
        cmd = [
            "openclaw",
            "agent",
            "--message", prompt,
            "--session-id", session_id,
            "--json"
        ]

        # Execute command
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise Exception(f"OpenClaw command failed: {error_msg}")

        # Parse response
        response_text = stdout.decode()

        # Try to extract JSON response if available
        try:
            # OpenClaw may output multiple lines, we want the agent response
            lines = response_text.strip().split('\n')
            for line in lines:
                if line.strip().startswith('{'):
                    response_data = json.loads(line)
                    return response_data
        except json.JSONDecodeError:
            pass

        # Fallback: return raw text
        return {
            "response": response_text,
            "status": "completed"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "OpenClaw API Server",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    # Check if OpenClaw is configured
    config_path = f"{OPENCLAW_HOME}/openclaw.json"
    config_exists = os.path.exists(config_path)

    # Check if sessions directory exists
    sessions_dir_exists = os.path.exists(SESSIONS_DIR)

    return {
        "status": "healthy",
        "openclaw_configured": config_exists,
        "sessions_dir_ready": sessions_dir_exists
    }


@app.post("/prompt", response_model=SessionResponse)
async def send_prompt(request: PromptRequest):
    """Send a prompt to OpenClaw"""
    session_id = request.session_id

    # Create new session if requested or no session ID provided
    if request.create_new_session or not session_id:
        session_id = generate_session_id()
        active_sessions[session_id] = {
            "created_at": datetime.utcnow().isoformat(),
            "message_count": 0
        }

    # Validate session ID format
    if not session_id:
        raise HTTPException(status_code=400, detail="Session ID is required")

    try:
        # Send prompt to OpenClaw
        result = await send_prompt_to_openclaw(session_id, request.prompt)

        # Update session info
        if session_id in active_sessions:
            active_sessions[session_id]["message_count"] += 1
            active_sessions[session_id]["updated_at"] = datetime.utcnow().isoformat()

        return SessionResponse(
            session_id=session_id,
            response=result.get("response", str(result)),
            status=result.get("status", "completed")
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions", response_model=List[SessionInfo])
async def list_sessions():
    """List all available sessions"""
    session_files = get_all_session_files()
    sessions = []

    for file_path in session_files:
        session_id = os.path.basename(file_path).replace('.jsonl', '')

        # Get file stats
        stat = os.stat(file_path)
        created_at = datetime.fromtimestamp(stat.st_ctime).isoformat()
        updated_at = datetime.fromtimestamp(stat.st_mtime).isoformat()

        # Count messages
        message_count = await count_session_messages(file_path)

        sessions.append(SessionInfo(
            session_id=session_id,
            created_at=created_at,
            updated_at=updated_at,
            file_path=file_path,
            message_count=message_count
        ))

    # Sort by updated time (most recent first)
    sessions.sort(key=lambda x: x.updated_at or "", reverse=True)

    return sessions


@app.get("/sessions/{session_id}")
async def get_session_info(session_id: str):
    """Get information about a specific session"""
    session_file = get_session_file_path(session_id)

    if not os.path.exists(session_file):
        raise HTTPException(status_code=404, detail="Session not found")

    # Get file stats
    stat = os.stat(session_file)
    created_at = datetime.fromtimestamp(stat.st_ctime).isoformat()
    updated_at = datetime.fromtimestamp(stat.st_mtime).isoformat()

    # Count messages
    message_count = await count_session_messages(session_file)

    # Get metadata if available
    metadata = await read_session_metadata(session_id)

    return {
        "session_id": session_id,
        "created_at": created_at,
        "updated_at": updated_at,
        "file_path": session_file,
        "message_count": message_count,
        "metadata": metadata
    }


@app.get("/sessions/{session_id}/export")
async def export_session(session_id: str):
    """Export a session JSONL file"""
    session_file = get_session_file_path(session_id)

    if not os.path.exists(session_file):
        raise HTTPException(status_code=404, detail="Session not found")

    return FileResponse(
        path=session_file,
        filename=f"session_{session_id}.jsonl",
        media_type="application/x-ndjson"
    )


@app.get("/sessions/{session_id}/history")
async def get_session_history(session_id: str):
    """Get complete session history including all tool calls"""
    session_file = get_session_file_path(session_id)

    if not os.path.exists(session_file):
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        # Read all lines from the session JSONL file
        history = []
        async with aiofiles.open(session_file, 'r') as f:
            async for line in f:
                line = line.strip()
                if line:
                    try:
                        record = json.loads(line)
                        history.append(record)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse line in session {session_id}: {e}")
                        continue

        return {
            "session_id": session_id,
            "total_records": len(history),
            "history": history
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read session history: {str(e)}")


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session"""
    session_file = get_session_file_path(session_id)

    if not os.path.exists(session_file):
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        os.remove(session_file)

        # Remove from active sessions if present
        if session_id in active_sessions:
            del active_sessions[session_id]

        return {"status": "deleted", "session_id": session_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sessions/{session_id}/clear")
async def clear_session(session_id: str):
    """Clear a session (delete and recreate)"""
    session_file = get_session_file_path(session_id)

    # Delete if exists
    if os.path.exists(session_file):
        os.remove(session_file)

    # Remove from active sessions
    if session_id in active_sessions:
        del active_sessions[session_id]

    # Recreate session
    active_sessions[session_id] = {
        "created_at": datetime.utcnow().isoformat(),
        "message_count": 0
    }

    return {"status": "cleared", "session_id": session_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
