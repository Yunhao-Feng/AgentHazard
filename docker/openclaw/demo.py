#!/usr/bin/env python3
"""
OpenClaw 演示程序
- 自动启动容器
- 提供 Web UI 进行交互
- 支持对话历史导出
"""
import subprocess
import time
import webbrowser
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import uvicorn
import requests
import logging
import json
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DemoContainer:
    """管理演示容器的生命周期"""

    def __init__(self, api_port=8000, gateway_port=18789):
        self.container_name = "openclaw-demo"
        self.api_port = api_port
        self.gateway_port = gateway_port
        self.api_url = f"http://localhost:{api_port}"

    def start(self):
        """启动容器"""
        # 先尝试停止旧容器
        self.stop()

        logger.info(f"启动容器: {self.container_name}")
        cmd = [
            "docker", "run",
            "-d",
            "--name", self.container_name,
            "-p", f"{self.api_port}:8000",
            "-p", f"{self.gateway_port}:18789",
            "-v", f"{Path.cwd()}/config.yaml:/app/configs/config.yaml:ro",
            "-e", "OPENCLAW_GATEWAY_TOKEN=default-token",
            "clawmonitor-openclaw:latest"
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True)
            logger.info(f"✓ 容器已启动: {self.container_name}")
            logger.info(f"  API: http://localhost:{self.api_port}")
            logger.info(f"  Gateway: http://localhost:{self.gateway_port}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ 启动容器失败: {e.stderr.decode()}")
            return False

    def stop(self):
        """停止并删除容器"""
        subprocess.run(
            ["docker", "rm", "-f", self.container_name],
            capture_output=True,
            check=False
        )

    def wait_ready(self, timeout=60):
        """等待容器就绪"""
        logger.info("等待容器就绪...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"{self.api_url}/health", timeout=2)
                if response.status_code == 200:
                    logger.info("✓ 容器已就绪")
                    return True
            except requests.exceptions.RequestException:
                pass
            time.sleep(2)

        logger.error("❌ 容器启动超时")
        return False


# FastAPI 应用
app = FastAPI(title="OpenClaw Demo")

# 容器实例（全局）
container = None


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    session_id: str


@app.on_event("startup")
async def startup():
    """启动时初始化容器"""
    global container
    container = DemoContainer()

    if not container.start():
        raise RuntimeError("无法启动容器")

    if not container.wait_ready():
        raise RuntimeError("容器启动超时")


@app.on_event("shutdown")
async def shutdown():
    """关闭时清理容器"""
    if container:
        logger.info("清理容器...")
        container.stop()


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """提供聊天界面"""
    html_content = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenClaw Demo</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }

        .container {
            width: 90%;
            max-width: 1000px;
            height: 90vh;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .header h1 {
            font-size: 24px;
            font-weight: 600;
        }

        .header-buttons {
            display: flex;
            gap: 10px;
        }

        .header-btn {
            background: rgba(255, 255, 255, 0.2);
            border: 2px solid white;
            color: white;
            padding: 10px 20px;
            border-radius: 10px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.3s;
        }

        .header-btn:hover {
            background: white;
            color: #667eea;
        }

        .header-btn.active {
            background: white;
            color: #667eea;
        }

        .chat-area {
            flex: 1;
            overflow-y: auto;
            padding: 30px;
            background: #f7f9fc;
        }

        .message {
            display: flex;
            margin-bottom: 20px;
            animation: fadeIn 0.3s;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .message.user {
            flex-direction: row-reverse;
        }

        .avatar {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            flex-shrink: 0;
        }

        .message.user .avatar {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            margin-left: 15px;
        }

        .message.assistant .avatar {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            margin-right: 15px;
        }

        .message-content {
            max-width: 70%;
            padding: 15px 20px;
            border-radius: 18px;
            line-height: 1.6;
            word-wrap: break-word;
            white-space: pre-wrap;
        }

        .message-content ul, .message-content ol {
            margin: 10px 0;
            padding-left: 20px;
        }

        .message-content li {
            margin: 5px 0;
        }

        .message-content strong {
            font-weight: 600;
        }

        .message-content code {
            background: rgba(0, 0, 0, 0.1);
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }

        .message.user .message-content code {
            background: rgba(255, 255, 255, 0.2);
        }

        .message.user .message-content {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }

        .message.assistant .message-content {
            background: white;
            color: #333;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
        }

        .input-area {
            padding: 20px 30px;
            background: white;
            border-top: 1px solid #e0e0e0;
            display: flex;
            gap: 15px;
        }

        #messageInput {
            flex: 1;
            padding: 15px 20px;
            border: 2px solid #e0e0e0;
            border-radius: 25px;
            font-size: 15px;
            outline: none;
            transition: border 0.3s;
        }

        #messageInput:focus {
            border-color: #667eea;
        }

        #sendBtn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 15px 30px;
            border-radius: 25px;
            cursor: pointer;
            font-size: 15px;
            font-weight: 600;
            transition: transform 0.2s, box-shadow 0.2s;
        }

        #sendBtn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }

        #sendBtn:active {
            transform: translateY(0);
        }

        #sendBtn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }

        .typing-indicator {
            display: none;
            padding: 15px 20px;
            background: white;
            border-radius: 18px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
            width: fit-content;
        }

        .typing-indicator.show {
            display: block;
        }

        .typing-indicator span {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #667eea;
            margin: 0 2px;
            animation: typing 1.4s infinite;
        }

        .typing-indicator span:nth-child(2) {
            animation-delay: 0.2s;
        }

        .typing-indicator span:nth-child(3) {
            animation-delay: 0.4s;
        }

        @keyframes typing {
            0%, 60%, 100% { transform: translateY(0); }
            30% { transform: translateY(-10px); }
        }

        /* Modal Styles */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.5);
            animation: fadeIn 0.3s;
        }

        .modal-content {
            background: white;
            margin: 10% auto;
            padding: 30px;
            border-radius: 20px;
            width: 90%;
            max-width: 500px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
        }

        .modal h2 {
            margin-bottom: 20px;
            color: #333;
        }

        .modal input {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 14px;
            margin-bottom: 20px;
        }

        .modal-buttons {
            display: flex;
            gap: 10px;
            justify-content: flex-end;
        }

        .modal-btn {
            padding: 10px 20px;
            border-radius: 10px;
            border: none;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.3s;
        }

        .modal-btn.primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }

        .modal-btn.secondary {
            background: #e0e0e0;
            color: #666;
        }

        .modal-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.2);
        }

        /* Scrollbar */
        .chat-area::-webkit-scrollbar {
            width: 8px;
        }

        .chat-area::-webkit-scrollbar-track {
            background: #f1f1f1;
        }

        .chat-area::-webkit-scrollbar-thumb {
            background: #667eea;
            border-radius: 10px;
        }

        .chat-area::-webkit-scrollbar-thumb:hover {
            background: #764ba2;
        }

        /* Terminal Styles */
        .terminal-area {
            display: none;
            flex: 1;
            background: #1e1e1e;
            padding: 20px;
            overflow-y: auto;
            font-family: 'Courier New', 'Monaco', monospace;
            font-size: 14px;
        }

        .terminal-area.active {
            display: block;
        }

        .terminal-line {
            color: #00ff00;
            margin-bottom: 5px;
            white-space: pre-wrap;
            word-wrap: break-word;
        }

        .terminal-line.command {
            color: #66d9ef;
        }

        .terminal-line.output {
            color: #a6e22e;
        }

        .terminal-line.error {
            color: #f92672;
        }

        .terminal-prompt {
            color: #66d9ef;
            display: inline-block;
            margin-right: 5px;
        }

        .terminal-area::-webkit-scrollbar {
            width: 8px;
        }

        .terminal-area::-webkit-scrollbar-track {
            background: #2d2d2d;
        }

        .terminal-area::-webkit-scrollbar-thumb {
            background: #666;
            border-radius: 10px;
        }

        .terminal-area::-webkit-scrollbar-thumb:hover {
            background: #888;
        }

        .view-hidden {
            display: none !important;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 OpenClaw Demo</h1>
            <div class="header-buttons">
                <button class="header-btn active" id="chatModeBtn" onclick="switchMode('chat')">💬 聊天</button>
                <button class="header-btn" id="terminalModeBtn" onclick="switchMode('terminal')">⌨️ 终端</button>
                <button class="header-btn" onclick="showExportModal()">📥 导出</button>
            </div>
        </div>

        <!-- Chat Area -->
        <div class="chat-area active" id="chatArea">
            <div class="message assistant">
                <div class="avatar">🤖</div>
                <div class="message-content">
                    你好！我是 OpenClaw AI Agent。我可以帮你执行各种任务，比如文件操作、代码编写、系统命令等。有什么我可以帮你的吗？
                </div>
            </div>
        </div>

        <!-- Terminal Area -->
        <div class="terminal-area" id="terminalArea">
            <div class="terminal-line">
                <span style="color: #f92672;">Welcome to OpenClaw Container Terminal</span>
            </div>
            <div class="terminal-line">
                <span style="color: #66d9ef;">Type your commands below. Use 'clear' to clear the terminal.</span>
            </div>
            <div class="terminal-line" style="margin-bottom: 15px;">
                <span style="color: #888;">─────────────────────────────────────────────────────</span>
            </div>
        </div>

        <div class="input-area">
            <input type="text" id="messageInput" placeholder="输入消息..." onkeypress="handleKeyPress(event)">
            <button id="sendBtn" onclick="sendMessage()">发送</button>
        </div>
    </div>

    <!-- Export Modal -->
    <div id="exportModal" class="modal">
        <div class="modal-content">
            <h2>📥 导出对话历史</h2>
            <label for="exportPath">保存路径（留空则保存到当前目录）:</label>
            <input type="text" id="exportPath" placeholder="例如: /path/to/save/chat_history.jsonl">
            <div class="modal-buttons">
                <button class="modal-btn secondary" onclick="closeExportModal()">取消</button>
                <button class="modal-btn primary" onclick="exportChat()">导出</button>
            </div>
        </div>
    </div>

    <script>
        let sessionId = null;
        let currentMode = 'chat';

        function switchMode(mode) {
            currentMode = mode;
            const chatArea = document.getElementById('chatArea');
            const terminalArea = document.getElementById('terminalArea');
            const messageInput = document.getElementById('messageInput');
            const sendBtn = document.getElementById('sendBtn');
            const chatModeBtn = document.getElementById('chatModeBtn');
            const terminalModeBtn = document.getElementById('terminalModeBtn');

            if (mode === 'chat') {
                chatArea.classList.add('active');
                terminalArea.classList.remove('active');
                messageInput.placeholder = '输入消息...';
                sendBtn.textContent = '发送';
                chatModeBtn.classList.add('active');
                terminalModeBtn.classList.remove('active');
            } else {
                chatArea.classList.remove('active');
                terminalArea.classList.add('active');
                messageInput.placeholder = '输入命令...';
                sendBtn.textContent = '执行';
                chatModeBtn.classList.remove('active');
                terminalModeBtn.classList.add('active');
            }

            messageInput.focus();
        }

        function addMessage(content, isUser) {
            const chatArea = document.getElementById('chatArea');
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${isUser ? 'user' : 'assistant'}`;

            const avatar = document.createElement('div');
            avatar.className = 'avatar';
            avatar.textContent = isUser ? '👤' : '🤖';

            const messageContent = document.createElement('div');
            messageContent.className = 'message-content';

            // 简单处理 markdown 样式文本
            let formattedContent = content
                // 处理加粗 **text**
                .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                // 处理斜体 *text*
                .replace(/\*(.+?)\*/g, '<em>$1</em>')
                // 处理行内代码 `code`
                .replace(/`(.+?)`/g, '<code>$1</code>')
                // 处理列表项 - item 或 * item
                .replace(/^[\-\*]\s+(.+)$/gm, '<li>$1</li>');

            // 如果有列表项，包裹在 ul 中
            if (formattedContent.includes('<li>')) {
                formattedContent = formattedContent.replace(/(<li>.+<\/li>\s*)+/gs, '<ul>$&</ul>');
            }

            messageContent.innerHTML = formattedContent;

            messageDiv.appendChild(avatar);
            messageDiv.appendChild(messageContent);
            chatArea.appendChild(messageDiv);
            chatArea.scrollTop = chatArea.scrollHeight;
        }

        function showTyping() {
            const chatArea = document.getElementById('chatArea');
            const typingDiv = document.createElement('div');
            typingDiv.className = 'message assistant';
            typingDiv.id = 'typingIndicator';

            const avatar = document.createElement('div');
            avatar.className = 'avatar';
            avatar.textContent = '🤖';

            const typingContent = document.createElement('div');
            typingContent.className = 'typing-indicator show';
            typingContent.innerHTML = '<span></span><span></span><span></span>';

            typingDiv.appendChild(avatar);
            typingDiv.appendChild(typingContent);
            chatArea.appendChild(typingDiv);
            chatArea.scrollTop = chatArea.scrollHeight;
        }

        function hideTyping() {
            const typingIndicator = document.getElementById('typingIndicator');
            if (typingIndicator) {
                typingIndicator.remove();
            }
        }

        function addTerminalLine(content, type = 'output') {
            const terminalArea = document.getElementById('terminalArea');
            const line = document.createElement('div');
            line.className = `terminal-line ${type}`;

            if (type === 'command') {
                line.innerHTML = `<span class="terminal-prompt">root@openclaw:~$</span> ${escapeHtml(content)}`;
            } else {
                line.textContent = content;
            }

            terminalArea.appendChild(line);
            terminalArea.scrollTop = terminalArea.scrollHeight;
        }

        function clearTerminal() {
            const terminalArea = document.getElementById('terminalArea');
            terminalArea.innerHTML = `
                <div class="terminal-line">
                    <span style="color: #f92672;">Welcome to OpenClaw Container Terminal</span>
                </div>
                <div class="terminal-line">
                    <span style="color: #66d9ef;">Type your commands below. Use 'clear' to clear the terminal.</span>
                </div>
                <div class="terminal-line" style="margin-bottom: 15px;">
                    <span style="color: #888;">─────────────────────────────────────────────────────</span>
                </div>
            `;
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        async function executeCommand(command) {
            const sendBtn = document.getElementById('sendBtn');
            sendBtn.disabled = true;

            // Handle built-in clear command
            if (command === 'clear') {
                clearTerminal();
                sendBtn.disabled = false;
                return;
            }

            // Add command to terminal
            addTerminalLine(command, 'command');

            try {
                const response = await fetch('/api/terminal', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ command: command })
                });

                const data = await response.json();

                if (response.ok) {
                    if (data.output) {
                        addTerminalLine(data.output, 'output');
                    }
                    if (data.error) {
                        addTerminalLine(data.error, 'error');
                    }
                } else {
                    addTerminalLine(`Error: ${data.detail || '命令执行失败'}`, 'error');
                }
            } catch (error) {
                addTerminalLine(`Network error: ${error.message}`, 'error');
            } finally {
                sendBtn.disabled = false;
            }
        }

        async function sendMessage() {
            const input = document.getElementById('messageInput');
            const sendBtn = document.getElementById('sendBtn');
            const message = input.value.trim();

            if (!message) return;

            input.value = '';

            // Route to different handlers based on mode
            if (currentMode === 'terminal') {
                await executeCommand(message);
                input.focus();
                return;
            }

            // Chat mode
            sendBtn.disabled = true;
            addMessage(message, true);
            showTyping();

            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        message: message,
                        session_id: sessionId
                    })
                });

                const data = await response.json();

                if (response.ok) {
                    sessionId = data.session_id;
                    hideTyping();
                    addMessage(data.response, false);
                } else {
                    hideTyping();
                    addMessage(`错误: ${data.detail || '请求失败'}`, false);
                }
            } catch (error) {
                hideTyping();
                addMessage(`网络错误: ${error.message}`, false);
            } finally {
                sendBtn.disabled = false;
                input.focus();
            }
        }

        function handleKeyPress(event) {
            if (event.key === 'Enter') {
                sendMessage();
            }
        }

        function showExportModal() {
            if (!sessionId) {
                alert('还没有开始对话，无法导出！');
                return;
            }
            document.getElementById('exportModal').style.display = 'block';
        }

        function closeExportModal() {
            document.getElementById('exportModal').style.display = 'none';
        }

        async function exportChat() {
            const path = document.getElementById('exportPath').value.trim();

            try {
                const response = await fetch('/api/export', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        session_id: sessionId,
                        save_path: path || null
                    })
                });

                const data = await response.json();

                if (response.ok) {
                    alert(`✓ 导出成功！\n保存路径: ${data.file_path}`);
                    closeExportModal();
                } else {
                    alert(`导出失败: ${data.detail || '未知错误'}`);
                }
            } catch (error) {
                alert(`网络错误: ${error.message}`);
            }
        }

        // Close modal when clicking outside
        window.onclick = function(event) {
            const modal = document.getElementById('exportModal');
            if (event.target === modal) {
                closeExportModal();
            }
        }

        // Focus input on load
        document.getElementById('messageInput').focus();
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """处理聊天请求"""
    try:
        # 转发到容器的 API
        payload = {
            "prompt": request.message,
            "session_id": request.session_id,
            "create_new_session": request.session_id is None
        }

        response = requests.post(
            f"{container.api_url}/prompt",
            json=payload,
            timeout=300
        )

        if response.status_code == 200:
            data = response.json()

            # 提取实际的回复文本（处理可能的 JSON 响应格式）
            response_text = data["response"]

            # 如果响应是 JSON 字符串，尝试解析并提取 payloads[0].text
            try:
                if isinstance(response_text, str):
                    parsed = json.loads(response_text)
                    if "payloads" in parsed and len(parsed["payloads"]) > 0:
                        # 提取第一个 payload 的 text
                        response_text = parsed["payloads"][0].get("text", response_text)
            except (json.JSONDecodeError, KeyError, IndexError):
                # 如果解析失败，保持原样
                pass

            return ChatResponse(
                response=response_text,
                session_id=data["session_id"]
            )
        else:
            raise HTTPException(status_code=response.status_code, detail="容器 API 请求失败")

    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="请求超时")
    except Exception as e:
        logger.error(f"聊天请求失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ExportRequest(BaseModel):
    session_id: str
    save_path: Optional[str] = None


class TerminalRequest(BaseModel):
    command: str


class TerminalResponse(BaseModel):
    output: str
    error: str
    exit_code: int


@app.post("/api/export")
async def export_session(request: ExportRequest):
    """导出会话历史"""
    try:
        # 从容器获取完整历史
        response = requests.get(
            f"{container.api_url}/sessions/{request.session_id}/history",
            timeout=30
        )

        if response.status_code != 200:
            raise HTTPException(status_code=404, detail="会话不存在")

        history_data = response.json()

        # 确定保存路径
        if request.save_path:
            save_path = Path(request.save_path)
        else:
            save_path = Path.cwd() / f"{request.session_id}.jsonl"

        # 确保目录存在
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # 保存为 JSONL
        with open(save_path, 'w', encoding='utf-8') as f:
            for record in history_data['history']:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')

        logger.info(f"✓ 导出会话历史: {save_path}")
        return {"success": True, "file_path": str(save_path)}

    except Exception as e:
        logger.error(f"导出失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/terminal", response_model=TerminalResponse)
async def execute_terminal_command(request: TerminalRequest):
    """在容器中执行终端命令"""
    try:
        # 使用 docker exec 在容器中执行命令
        cmd = [
            "docker", "exec",
            container.container_name,
            "bash", "-c",
            request.command
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        return TerminalResponse(
            output=result.stdout,
            error=result.stderr,
            exit_code=result.returncode
        )

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="命令执行超时（30秒）")
    except Exception as e:
        logger.error(f"终端命令执行失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def main():
    """启动演示程序"""
    import sys

    print("=" * 60)
    print("OpenClaw 演示程序")
    print("=" * 60)
    print()

    # 启动 Web 服务器
    port = 8080
    print(f"🚀 启动 Web 服务器: http://localhost:{port}")
    print(f"📱 浏览器将自动打开...")
    print()
    print("按 Ctrl+C 停止")
    print("=" * 60)

    # 自动打开浏览器
    import threading
    def open_browser():
        time.sleep(5)  # 等待服务器启动
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=open_browser, daemon=True).start()

    # 启动服务器
    try:
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
    except KeyboardInterrupt:
        print("\n\n正在关闭...")
        sys.exit(0)


if __name__ == "__main__":
    main()
