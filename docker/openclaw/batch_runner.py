#!/usr/bin/env python3
"""
批量任务调度器
- 从 jsonl 读取任务
- 批量启动容器
- 异步并发执行多轮对话
- 自动重试机制
- 导出结果
"""
import json
import subprocess
import time
import requests
from pathlib import Path
from typing import List, Dict
import yaml
import asyncio
import aiohttp
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    after_log
)
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BatchRunner:
    def __init__(self, config_path="config.yaml", jsonl_path="Trasfer_decomposed_harm.jsonl"):
        # 加载配置
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.max_concurrent = self.config.get('max_concurrent', 5)
        self.jsonl_path = jsonl_path
        self.output_dir = Path("./batch_output")
        self.output_dir.mkdir(exist_ok=True)

        # 端口范围
        self.base_api_port = 8000
        self.base_gateway_port = 18789

        # 重试配置
        retry_config = self.config.get('retry', {})
        self.retry_prompt = retry_config.get('prompt', {
            'max_attempts': 3,
            'min_wait': 4,
            'max_wait': 10
        })
        self.retry_health = retry_config.get('health_check', {
            'max_attempts': 30,
            'min_wait': 2,
            'max_wait': 5
        })

    def load_tasks(self) -> List[Dict]:
        """加载所有任务"""
        tasks = []
        with open(self.jsonl_path, 'r') as f:
            for line in f:
                if line.strip():
                    tasks.append(json.loads(line))
        return tasks

    def start_container(self, task_id: str, api_port: int, gateway_port: int):
        """启动单个容器"""
        container_name = f"openclaw-task-{task_id}"

        cmd = [
            "docker", "run",
            "-d",  # 后台运行
            "--name", container_name,
            "-p", f"{api_port}:8000",
            "-p", f"{gateway_port}:18789",
            "-v", f"{Path.cwd()}/config.yaml:/app/configs/config.yaml:ro",
            "-e", "OPENCLAW_GATEWAY_TOKEN=default-token",
            "clawmonitor-openclaw:latest"
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True)
            print(f"✓ 启动容器: {container_name} (API:{api_port}, Gateway:{gateway_port})")
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ 启动容器失败: {e.stderr.decode()}")
            return False

    def stop_container(self, task_id: str):
        """停止并删除容器"""
        container_name = f"openclaw-task-{task_id}"
        subprocess.run(["docker", "rm", "-f", container_name],
                    capture_output=True, check=False)
        print(f"✓ 销毁容器: {container_name}")

    async def _check_health(self, session: aiohttp.ClientSession, url: str):
        """健康检查（带重试）"""
        # 动态创建重试装饰器
        retry_decorator = retry(
            stop=stop_after_attempt(self.retry_health['max_attempts']),
            wait=wait_exponential(
                multiplier=1,
                min=self.retry_health['min_wait'],
                max=self.retry_health['max_wait']
            ),
            retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
            before_sleep=before_sleep_log(logger, logging.WARNING)
        )

        @retry_decorator
        async def _do_check():
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as response:
                response.raise_for_status()
                return response.status == 200

        return await _do_check()

    async def wait_for_ready(self, api_port: int, timeout=60):
        """等待容器就绪（异步）"""
        url = f"http://localhost:{api_port}/health"

        try:
            async with aiohttp.ClientSession() as session:
                await self._check_health(session, url)
                return True
        except Exception as e:
            logger.error(f"容器 {api_port} 未就绪: {e}")
            return False

    async def _send_prompt(self, session: aiohttp.ClientSession, url: str, payload: Dict) -> Dict:
        """发送 prompt 请求（带重试）"""
        # 动态创建重试装饰器
        retry_decorator = retry(
            stop=stop_after_attempt(self.retry_prompt['max_attempts']),
            wait=wait_exponential(
                multiplier=1,
                min=self.retry_prompt['min_wait'],
                max=self.retry_prompt['max_wait']
            ),
            retry=retry_if_exception_type((
                aiohttp.ClientError,
                asyncio.TimeoutError,
                aiohttp.ServerTimeoutError
            )),
            before_sleep=before_sleep_log(logger, logging.WARNING)
        )

        @retry_decorator
        async def _do_send():
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=300)
            ) as response:
                response.raise_for_status()
                return await response.json()

        return await _do_send()

    async def execute_task(self, task: Dict, api_port: int) -> Dict:
        """执行单个任务（多轮对话，异步）"""
        record_id = task['record_id']
        turns = json.loads(task['deomposed_query'])['turns']

        print(f"\n=== 执行任务: {record_id} ===")

        # 创建新 session
        session_id = None
        responses = []

        async with aiohttp.ClientSession() as session:
            for i, turn in enumerate(turns, 1):
                prompt = turn['output']
                print(f"[{record_id}] [{i}/{len(turns)}] 发送 prompt...")

                try:
                    payload = {"prompt": prompt}
                    if session_id:
                        payload["session_id"] = session_id
                    else:
                        payload["create_new_session"] = True

                    result = await self._send_prompt(
                        session,
                        f"http://localhost:{api_port}/prompt",
                        payload
                    )

                    if not session_id:
                        session_id = result["session_id"]

                    responses.append({
                        "turn": i,
                        "thought": turn['thought'],
                        "prompt": prompt,
                        "response": result["response"]
                    })

                except Exception as e:
                    logger.error(f"[{record_id}] 第 {i} 轮失败（重试后仍失败）: {e}")
                    responses.append({
                        "turn": i,
                        "thought": turn['thought'],
                        "prompt": prompt,
                        "error": str(e)
                    })

            # 任务完成后，导出完整的 session history (包含所有工具调用轨迹)
            full_session_history = None
            if session_id:
                try:
                    print(f"[{record_id}] 导出完整 session 历史记录...")
                    async with session.get(
                        f"http://localhost:{api_port}/sessions/{session_id}/history",
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as resp:
                        if resp.status == 200:
                            full_session_history = await resp.json()
                        else:
                            logger.warning(f"[{record_id}] 获取 session 历史失败: HTTP {resp.status}")
                except Exception as e:
                    logger.error(f"[{record_id}] 导出 session 历史失败: {e}")

        # 构建结果
        result = {
            "record_id": record_id,
            "session_id": session_id,
            "instruction": task['instruction'],
            "category": task['category'],
            "total_turns": len(turns),
            "turns": responses,
            "full_session_history": full_session_history,  # 包含完整的工具调用轨迹
            "original_task": task
        }

        return result

    def export_result(self, result: Dict):
        """导出单个任务结果"""
        record_id = result['record_id']

        # 导出简要结果（保持向后兼容）
        output_file = self.output_dir / f"{record_id}.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"✓ 导出结果: {output_file}")

        # 如果有完整的 session history，单独导出为 JSONL
        if result.get('full_session_history'):
            history_file = self.output_dir / f"{record_id}_session.jsonl"
            try:
                with open(history_file, 'w', encoding='utf-8') as f:
                    for record in result['full_session_history']['history']:
                        f.write(json.dumps(record, ensure_ascii=False) + '\n')
                print(f"✓ 导出完整历史: {history_file}")
            except Exception as e:
                logger.error(f"导出完整历史失败: {e}")

    async def run_batch(self, tasks: List[Dict]):
        """运行一个批次（异步并发）"""
        batch_size = min(len(tasks), self.max_concurrent)

        print(f"\n{'='*60}")
        print(f"批次大小: {batch_size}")
        print(f"{'='*60}")

        # 启动容器
        running_tasks = []
        for i, task in enumerate(tasks[:batch_size]):
            record_id = task['record_id']
            api_port = self.base_api_port + i
            gateway_port = self.base_gateway_port + i

            if self.start_container(record_id, api_port, gateway_port):
                running_tasks.append({
                    "task": task,
                    "api_port": api_port,
                    "record_id": record_id
                })

        # 并发等待所有容器就绪
        print(f"\n⏳ 等待容器就绪...")
        time.sleep(5)
        ready_results = await asyncio.gather(
            *[self.wait_for_ready(item["api_port"]) for item in running_tasks],
            return_exceptions=True
        )

        for item, ready in zip(running_tasks, ready_results):
            if ready:
                print(f"✓ 容器就绪: {item['record_id']}")
            else:
                print(f"❌ 容器超时: {item['record_id']}")

        await asyncio.sleep(5)  # 额外等待

        # 并发执行所有任务
        print(f"\n🚀 开始并发执行 {len(running_tasks)} 个任务...")
        results = await asyncio.gather(
            *[self.execute_task(item["task"], item["api_port"]) for item in running_tasks],
            return_exceptions=True
        )

        # 导出结果
        for item, result in zip(running_tasks, results):
            if isinstance(result, Exception):
                print(f"❌ 任务执行失败: {item['record_id']}, {result}")
            else:
                self.export_result(result)

        # 销毁容器
        print(f"\n🗑️   销毁批次容器...")
        for item in running_tasks:
            self.stop_container(item["record_id"])

        return batch_size

    async def run(self):
        """运行所有任务（异步）"""
        tasks = self.load_tasks()
        total = len(tasks)
        completed = 0

        print(f"\n{'='*60}")
        print(f"批量任务执行器（异步并发）")
        print(f"{'='*60}")
        print(f"总任务数: {total}")
        print(f"并发数: {self.max_concurrent}")
        print(f"输出目录: {self.output_dir}")
        print(f"{'='*60}\n")

        while completed < total:
            remaining_tasks = tasks[completed:]
            batch_size = await self.run_batch(remaining_tasks)
            completed += batch_size

            print(f"\n✅ 已完成: {completed}/{total}")

            if completed < total:
                print(f"\n⏸️   等待5秒后继续...\n")
                await asyncio.sleep(5)

        print(f"\n{'='*60}")
        print(f"🎉 所有任务完成！")
        print(f"{'='*60}")
        print(f"结果保存在: {self.output_dir}")


if __name__ == "__main__":
    runner = BatchRunner()
    asyncio.run(runner.run())