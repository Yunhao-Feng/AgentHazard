#!/usr/bin/env python3
"""
可视化批量任务调度器
- 每个容器对应一个网页界面
- 实时显示多轮对话过程
- 自动注入和显示 prompt
- 任务完成后自动关闭
"""
import json
import subprocess
import time
import webbrowser
import asyncio
import yaml
from pathlib import Path
from typing import List, Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn
import aiohttp
import logging
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ===== 全局状态管理 =====
class TaskManager:
    """管理所有正在运行的任务"""
    def __init__(self):
        self.tasks = {}  # task_id -> task_info
        self.websockets = {}  # task_id -> websocket

    def register_task(self, task_id: str, task_info: Dict):
        self.tasks[task_id] = task_info

    def register_websocket(self, task_id: str, websocket: WebSocket):
        self.websockets[task_id] = websocket

    def unregister_websocket(self, task_id: str):
        if task_id in self.websockets:
            del self.websockets[task_id]

    async def send_message(self, task_id: str, message: Dict):
        """向特定任务的网页发送消息"""
        if task_id in self.websockets:
            try:
                await self.websockets[task_id].send_json(message)
            except Exception as e:
                logger.error(f"发送消息失败 [{task_id}]: {e}")


task_manager = TaskManager()


# ===== FastAPI 应用 =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    yield
    # 清理所有容器
    logger.info("清理所有容器...")


app = FastAPI(lifespan=lifespan)


@app.get("/task/{task_id}", response_class=HTMLResponse)
async def get_task_page(task_id: str):
    """为每个任务生成独立的网页"""
    task_info = task_manager.tasks.get(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="任务不存在")

    html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Task {task_id} - OpenClaw Monitor</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }}

        .container {{
            width: 100%;
            max-width: 1200px;
            height: 95vh;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}

        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .header-left {{
            display: flex;
            flex-direction: column;
            gap: 5px;
        }}

        .header h1 {{
            font-size: 24px;
            font-weight: 600;
        }}

        .task-info {{
            font-size: 14px;
            opacity: 0.9;
        }}

        .status-badge {{
            padding: 8px 16px;
            border-radius: 20px;
            background: rgba(255, 255, 255, 0.2);
            font-size: 14px;
            font-weight: 600;
        }}

        .status-badge.running {{
            background: #4caf50;
        }}

        .status-badge.waiting {{
            background: #ff9800;
        }}

        .status-badge.completed {{
            background: #2196f3;
        }}

        .chat-area {{
            flex: 1;
            overflow-y: auto;
            padding: 30px;
            background: #f7f9fc;
        }}

        .message {{
            display: flex;
            margin-bottom: 20px;
            animation: fadeIn 0.3s;
        }}

        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        .message.user {{
            flex-direction: row-reverse;
        }}

        .avatar {{
            width: 40px;
            height: 40px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            flex-shrink: 0;
        }}

        .message.user .avatar {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            margin-left: 15px;
        }}

        .message.assistant .avatar {{
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            margin-right: 15px;
        }}

        .message.system .avatar {{
            background: linear-gradient(135deg, #ffa726 0%, #fb8c00 100%);
            margin-right: 15px;
        }}

        .message-content {{
            max-width: 70%;
            padding: 15px 20px;
            border-radius: 18px;
            line-height: 1.6;
            word-wrap: break-word;
            white-space: pre-wrap;
        }}

        .message.user .message-content {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}

        .message.assistant .message-content {{
            background: white;
            color: #333;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
        }}

        .message.system .message-content {{
            background: #fff3e0;
            color: #e65100;
            font-weight: 500;
        }}

        .turn-indicator {{
            display: inline-block;
            background: rgba(0, 0, 0, 0.1);
            padding: 4px 10px;
            border-radius: 10px;
            font-size: 12px;
            font-weight: 600;
            margin-bottom: 8px;
        }}

        .typing-indicator {{
            display: none;
            padding: 15px 20px;
            background: white;
            border-radius: 18px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
            width: fit-content;
        }}

        .typing-indicator.show {{
            display: block;
        }}

        .typing-indicator span {{
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #667eea;
            margin: 0 2px;
            animation: typing 1.4s infinite;
        }}

        .typing-indicator span:nth-child(2) {{
            animation-delay: 0.2s;
        }}

        .typing-indicator span:nth-child(3) {{
            animation-delay: 0.4s;
        }}

        @keyframes typing {{
            0%, 60%, 100% {{ transform: translateY(0); }}
            30% {{ transform: translateY(-10px); }}
        }}

        .chat-area::-webkit-scrollbar {{
            width: 8px;
        }}

        .chat-area::-webkit-scrollbar-track {{
            background: #f1f1f1;
        }}

        .chat-area::-webkit-scrollbar-thumb {{
            background: #667eea;
            border-radius: 10px;
        }}

        .closing-overlay {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.8);
            z-index: 9999;
            justify-content: center;
            align-items: center;
            flex-direction: column;
            color: white;
        }}

        .closing-overlay.show {{
            display: flex;
        }}

        .closing-overlay h2 {{
            font-size: 48px;
            margin-bottom: 20px;
        }}

        .closing-overlay p {{
            font-size: 24px;
            opacity: 0.8;
        }}

        .countdown {{
            font-size: 72px;
            font-weight: bold;
            margin-top: 30px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-left">
                <h1>🤖 Task {task_id}</h1>
                <div class="task-info">
                    <strong>Category:</strong> {task_info.get('category', 'N/A')} |
                    <strong>Port:</strong> {task_info.get('api_port', 'N/A')}
                </div>
            </div>
            <div class="status-badge waiting" id="statusBadge">等待中...</div>
        </div>

        <div class="chat-area" id="chatArea">
            <div class="message system">
                <div class="avatar">📋</div>
                <div class="message-content">
                    <strong>任务初始化</strong><br>
                    Record ID: {task_id}<br>
                    容器已启动，等待就绪...
                </div>
            </div>
        </div>
    </div>

    <div class="closing-overlay" id="closingOverlay">
        <h2>✅ 任务完成</h2>
        <p>窗口将在 5 秒后自动关闭</p>
        <div class="countdown" id="countdown">5</div>
    </div>

    <script>
        const taskId = "{task_id}";
        const ws = new WebSocket(`ws://localhost:8080/ws/${{taskId}}`);
        const chatArea = document.getElementById('chatArea');
        const statusBadge = document.getElementById('statusBadge');
        const closingOverlay = document.getElementById('closingOverlay');
        const countdownEl = document.getElementById('countdown');

        ws.onopen = () => {{
            console.log('WebSocket connected');
        }};

        ws.onmessage = (event) => {{
            const data = JSON.parse(event.data);
            handleMessage(data);
        }};

        ws.onerror = (error) => {{
            console.error('WebSocket error:', error);
        }};

        ws.onclose = () => {{
            console.log('WebSocket closed');
        }};

        function handleMessage(data) {{
            switch(data.type) {{
                case 'status':
                    updateStatus(data.status);
                    break;
                case 'system':
                    addSystemMessage(data.message);
                    break;
                case 'turn_start':
                    addTurnStart(data.turn, data.total_turns);
                    break;
                case 'user_message':
                    addUserMessage(data.message, data.turn);
                    break;
                case 'assistant_thinking':
                    showTyping();
                    break;
                case 'assistant_message':
                    hideTyping();
                    addAssistantMessage(data.message);
                    break;
                case 'task_complete':
                    showClosingAnimation();
                    break;
            }}
        }}

        function updateStatus(status) {{
            statusBadge.textContent = status;
            statusBadge.className = 'status-badge';
            if (status.includes('运行中')) {{
                statusBadge.classList.add('running');
            }} else if (status.includes('完成')) {{
                statusBadge.classList.add('completed');
            }} else {{
                statusBadge.classList.add('waiting');
            }}
        }}

        function addSystemMessage(message) {{
            const messageDiv = document.createElement('div');
            messageDiv.className = 'message system';
            messageDiv.innerHTML = `
                <div class="avatar">ℹ️</div>
                <div class="message-content">${{escapeHtml(message)}}</div>
            `;
            chatArea.appendChild(messageDiv);
            scrollToBottom();
        }}

        function addTurnStart(turn, total) {{
            const messageDiv = document.createElement('div');
            messageDiv.className = 'message system';
            messageDiv.innerHTML = `
                <div class="avatar">🔄</div>
                <div class="message-content">
                    <span class="turn-indicator">第 ${{turn}} / ${{total}} 轮</span>
                </div>
            `;
            chatArea.appendChild(messageDiv);
            scrollToBottom();
        }}

        function addUserMessage(message, turn) {{
            const messageDiv = document.createElement('div');
            messageDiv.className = 'message user';
            messageDiv.innerHTML = `
                <div class="avatar">👤</div>
                <div class="message-content">${{escapeHtml(message)}}</div>
            `;
            chatArea.appendChild(messageDiv);
            scrollToBottom();
        }}

        function showTyping() {{
            const typingDiv = document.createElement('div');
            typingDiv.className = 'message assistant';
            typingDiv.id = 'typingIndicator';
            typingDiv.innerHTML = `
                <div class="avatar">🤖</div>
                <div class="typing-indicator show">
                    <span></span><span></span><span></span>
                </div>
            `;
            chatArea.appendChild(typingDiv);
            scrollToBottom();
        }}

        function hideTyping() {{
            const typingIndicator = document.getElementById('typingIndicator');
            if (typingIndicator) {{
                typingIndicator.remove();
            }}
        }}

        function addAssistantMessage(message) {{
            const messageDiv = document.createElement('div');
            messageDiv.className = 'message assistant';
            messageDiv.innerHTML = `
                <div class="avatar">🤖</div>
                <div class="message-content">${{escapeHtml(message)}}</div>
            `;
            chatArea.appendChild(messageDiv);
            scrollToBottom();
        }}

        function showClosingAnimation() {{
            closingOverlay.classList.add('show');
            let count = 5;
            const interval = setInterval(() => {{
                count--;
                countdownEl.textContent = count;
                if (count === 0) {{
                    clearInterval(interval);
                    window.close();
                }}
            }}, 1000);
        }}

        function escapeHtml(text) {{
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }}

        function scrollToBottom() {{
            chatArea.scrollTop = chatArea.scrollHeight;
        }}
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html)


@app.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket 连接处理"""
    await websocket.accept()
    task_manager.register_websocket(task_id, websocket)
    logger.info(f"WebSocket 连接建立: {task_id}")

    try:
        while True:
            # 保持连接活跃
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        logger.info(f"WebSocket 断开: {task_id}")
    finally:
        task_manager.unregister_websocket(task_id)


# ===== 批处理逻辑 =====
class VisualBatchRunner:
    def __init__(self, config_path="config.yaml", jsonl_path="Trasfer_decomposed_harm.jsonl"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.max_concurrent = self.config.get('max_concurrent', 5)
        self.jsonl_path = jsonl_path
        self.output_dir = Path("./batch_output")
        self.output_dir.mkdir(exist_ok=True)

        self.base_api_port = 8000
        self.base_gateway_port = 18789
        self.web_port = 8080

    def load_tasks(self) -> List[Dict]:
        """加载所有任务"""
        tasks = []
        with open(self.jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    tasks.append(json.loads(line))
        return tasks

    def start_container(self, task_id: str, api_port: int, gateway_port: int):
        """启动单个容器"""
        container_name = f"openclaw-task-{task_id}"

        # 先停止旧容器
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            check=False
        )

        cmd = [
            "docker", "run",
            "-d",
            "--name", container_name,
            "-p", f"{api_port}:8000",
            "-p", f"{gateway_port}:18789",
            "-v", f"{Path.cwd()}/config.yaml:/app/configs/config.yaml:ro",
            "-e", "OPENCLAW_GATEWAY_TOKEN=default-token",
            "clawmonitor-openclaw:latest"
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True)
            logger.info(f"✓ 启动容器: {container_name} (API:{api_port})")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ 启动容器失败: {e.stderr.decode()}")
            return False

    def stop_container(self, task_id: str):
        """停止并删除容器"""
        container_name = f"openclaw-task-{task_id}"
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            check=False
        )
        logger.info(f"✓ 销毁容器: {container_name}")

    async def wait_for_ready(self, api_port: int, timeout=60):
        """等待容器就绪"""
        url = f"http://localhost:{api_port}/health"
        start_time = time.time()

        async with aiohttp.ClientSession() as session:
            while time.time() - start_time < timeout:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                        if resp.status == 200:
                            return True
                except:
                    pass
                await asyncio.sleep(2)

        return False

    async def execute_task(self, task: Dict, api_port: int, task_id: str):
        """执行单个任务并实时推送到网页"""
        record_id = task['record_id']
        turns = json.loads(task['deomposed_query'])['turns']

        # 通知网页：容器就绪
        await task_manager.send_message(task_id, {
            "type": "status",
            "status": "运行中"
        })
        await task_manager.send_message(task_id, {
            "type": "system",
            "message": f"容器已就绪，开始执行 {len(turns)} 轮对话..."
        })

        session_id = None
        responses = []

        async with aiohttp.ClientSession() as session:
            for i, turn in enumerate(turns, 1):
                prompt = turn['output']

                # 通知网页：新的一轮开始
                await task_manager.send_message(task_id, {
                    "type": "turn_start",
                    "turn": i,
                    "total_turns": len(turns)
                })

                # 显示用户消息（自动注入的 prompt）
                await task_manager.send_message(task_id, {
                    "type": "user_message",
                    "message": prompt,
                    "turn": i
                })

                # 显示 AI 正在思考
                await task_manager.send_message(task_id, {
                    "type": "assistant_thinking"
                })

                try:
                    payload = {"prompt": prompt}
                    if session_id:
                        payload["session_id"] = session_id
                    else:
                        payload["create_new_session"] = True

                    async with session.post(
                        f"http://localhost:{api_port}/prompt",
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=300)
                    ) as resp:
                        result = await resp.json()

                        if not session_id:
                            session_id = result["session_id"]

                        response_text = result["response"]

                        # 尝试解析 JSON 响应
                        try:
                            if isinstance(response_text, str):
                                parsed = json.loads(response_text)
                                if "payloads" in parsed and len(parsed["payloads"]) > 0:
                                    response_text = parsed["payloads"][0].get("text", response_text)
                        except:
                            pass

                        # 发送 AI 回复
                        await task_manager.send_message(task_id, {
                            "type": "assistant_message",
                            "message": response_text
                        })

                        responses.append({
                            "turn": i,
                            "thought": turn['thought'],
                            "prompt": prompt,
                            "response": response_text
                        })

                except Exception as e:
                    logger.error(f"[{record_id}] 第 {i} 轮失败: {e}")
                    await task_manager.send_message(task_id, {
                        "type": "assistant_message",
                        "message": f"❌ 错误: {str(e)}"
                    })
                    responses.append({
                        "turn": i,
                        "thought": turn['thought'],
                        "prompt": prompt,
                        "error": str(e)
                    })

        # 导出完整 session 历史
        full_session_history = None
        if session_id:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://localhost:{api_port}/sessions/{session_id}/history",
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as resp:
                        if resp.status == 200:
                            full_session_history = await resp.json()
            except Exception as e:
                logger.error(f"[{record_id}] 导出历史失败: {e}")

        # 构建结果
        result = {
            "record_id": record_id,
            "session_id": session_id,
            "instruction": task['instruction'],
            "category": task['category'],
            "total_turns": len(turns),
            "turns": responses,
            "full_session_history": full_session_history,
            "original_task": task
        }

        # 通知网页：任务完成
        await task_manager.send_message(task_id, {
            "type": "status",
            "status": "已完成"
        })
        await task_manager.send_message(task_id, {
            "type": "system",
            "message": "✅ 所有轮次执行完成，正在导出结果..."
        })

        return result

    def export_result(self, result: Dict):
        """导出任务结果"""
        record_id = result['record_id']

        output_file = self.output_dir / f"{record_id}.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"✓ 导出结果: {output_file}")

        if result.get('full_session_history'):
            history_file = self.output_dir / f"{record_id}_session.jsonl"
            try:
                with open(history_file, 'w', encoding='utf-8') as f:
                    for record in result['full_session_history']['history']:
                        f.write(json.dumps(record, ensure_ascii=False) + '\n')
                logger.info(f"✓ 导出完整历史: {history_file}")
            except Exception as e:
                logger.error(f"导出完整历史失败: {e}")

    async def run_batch(self, tasks: List[Dict]):
        """运行一个批次"""
        batch_size = min(len(tasks), self.max_concurrent)

        print(f"\n{'='*60}")
        print(f"批次大小: {batch_size}")
        print(f"{'='*60}")

        # 启动容器并注册任务
        running_tasks = []
        for i, task in enumerate(tasks[:batch_size]):
            record_id = str(task['record_id'])
            api_port = self.base_api_port + i
            gateway_port = self.base_gateway_port + i

            task_info = {
                "task": task,
                "api_port": api_port,
                "gateway_port": gateway_port,
                "record_id": record_id,
                "category": task.get('category', 'N/A')
            }

            if self.start_container(record_id, api_port, gateway_port):
                task_manager.register_task(record_id, task_info)
                running_tasks.append(task_info)

                # 打开浏览器窗口
                url = f"http://localhost:{self.web_port}/task/{record_id}"
                webbrowser.open(url)
                await asyncio.sleep(0.5)  # 错开浏览器打开时间

        # 等待容器就绪
        print(f"\n⏳ 等待容器就绪...")
        await asyncio.sleep(8)

        ready_results = await asyncio.gather(
            *[self.wait_for_ready(item["api_port"]) for item in running_tasks],
            return_exceptions=True
        )

        for item, ready in zip(running_tasks, ready_results):
            if ready:
                logger.info(f"✓ 容器就绪: {item['record_id']}")
            else:
                logger.error(f"❌ 容器超时: {item['record_id']}")

        await asyncio.sleep(3)

        # 并发执行所有任务
        print(f"\n🚀 开始并发执行 {len(running_tasks)} 个任务...")
        results = await asyncio.gather(
            *[self.execute_task(
                item["task"],
                item["api_port"],
                item["record_id"]
            ) for item in running_tasks],
            return_exceptions=True
        )

        # 导出结果
        for item, result in zip(running_tasks, results):
            if isinstance(result, Exception):
                logger.error(f"❌ 任务执行失败: {item['record_id']}, {result}")
            else:
                self.export_result(result)

        # 通知所有网页：任务完成，准备关闭
        for item in running_tasks:
            await task_manager.send_message(item["record_id"], {
                "type": "task_complete"
            })

        # 等待 5 秒后销毁容器
        print(f"\n⏸️   等待 5 秒后销毁容器...")
        await asyncio.sleep(5)

        for item in running_tasks:
            self.stop_container(item["record_id"])

        return batch_size

    async def run(self):
        """运行所有任务"""
        tasks = self.load_tasks()
        total = len(tasks)
        completed = 0

        print(f"\n{'='*60}")
        print(f"可视化批量任务执行器")
        print(f"{'='*60}")
        print(f"总任务数: {total}")
        print(f"并发数: {self.max_concurrent}")
        print(f"输出目录: {self.output_dir}")
        print(f"Web 服务: http://localhost:{self.web_port}")
        print(f"{'='*60}\n")

        while completed < total:
            remaining_tasks = tasks[completed:]
            batch_size = await self.run_batch(remaining_tasks)
            completed += batch_size

            print(f"\n✅ 已完成: {completed}/{total}")

            if completed < total:
                print(f"\n⏸️   等待 5 秒后继续下一批次...\n")
                await asyncio.sleep(5)

        print(f"\n{'='*60}")
        print(f"🎉 所有任务完成！")
        print(f"{'='*60}")
        print(f"结果保存在: {self.output_dir}")


# ===== 主程序 =====
async def main():
    """主函数"""
    runner = VisualBatchRunner()

    # 在后台启动 FastAPI 服务器
    config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="warning")
    server = uvicorn.Server(config)

    # 创建服务器任务
    server_task = asyncio.create_task(server.serve())

    # 等待服务器启动
    await asyncio.sleep(2)

    try:
        # 运行批处理任务
        await runner.run()
    finally:
        # 关闭服务器
        print("\n正在关闭 Web 服务器...")
        server.should_exit = True
        await server_task


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n用户中断，正在清理...")
