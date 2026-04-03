"""
Agent会话管理模块
处理与Agent的交互、记录执行轨迹
"""
import asyncio
import logging
from typing import List, Dict, Any
from datetime import datetime
from rock_hack.iflow_session import IflowClient

logger = logging.getLogger(__name__)


class AgentSession:
    """Agent会话管理器"""

    def __init__(self, config_file: str, max_retries: int = 3):
        """
        初始化Agent会话管理器

        Args:
            config_file: 配置文件路径
            max_retries: 最大重试次数
        """
        self.config_file = config_file
        self.max_retries = max_retries

    async def _execute_agent_turn(
        self,
        client: IflowClient,
        agent_name: str,
        turn_prompt: str,
        turn_idx: int
    ) -> str:
        """
        执行单轮 Agent 对话（超时 600s 返回固定提示）

        Args:
            client: IflowClient实例
            agent_name: Agent名称
            turn_prompt: 当前轮次的提示
            turn_idx: 轮次索引

        Returns:
            Agent的响应
        """
        TIMEOUT_SECONDS = 600
        TIMEOUT_MSG = "响应超时，超出最长响应时间"

        try:
            if agent_name == "claude":
                try:
                    response = await asyncio.wait_for(
                        client.claude.chat(turn_prompt),
                        timeout=TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Claude 响应超时（{TIMEOUT_SECONDS}s）")
                    return TIMEOUT_MSG

                # 检查是否有错误
                if hasattr(response, 'is_error') and response.is_error:
                    error_msg = getattr(response, 'error', 'Unknown error')
                    logger.error(f"Claude API 调用失败: {error_msg}")
                    return f"[ERROR] Claude API 调用失败: {error_msg}"

                # 检查 success 字段
                if hasattr(response, 'success') and not response.success:
                    error_msg = getattr(response, 'error', 'API call was not successful')
                    logger.error(f"Claude API 返回失败状态: {error_msg}")
                    return f"[ERROR] Claude API 返回失败: {error_msg}"

                # 正常情况：尝试多种方式获取响应内容
                for attr in ['result', 'content', 'text', 'message', 'output']:
                    if hasattr(response, attr) and getattr(response, attr):
                        content = getattr(response, attr)
                        logger.info(f"Claude 响应成功（从 {attr} 字段），内容长度: {len(content)}")
                        return content

                logger.warning("Claude 响应对象没有找到有效内容")
                return f"[WARNING] Claude 响应为空或格式异常: {str(response)}"

            elif agent_name == "openhands":
                try:
                    response = await asyncio.wait_for(
                        client.openhands.chat(turn_prompt),
                        timeout=TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"OpenHands 响应超时（{TIMEOUT_SECONDS}s）")
                    return TIMEOUT_MSG
                return response.result

            elif agent_name == "iflow":
                try:
                    response = await asyncio.wait_for(
                        client.chat(turn_prompt),
                        timeout=TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"iFlow 响应超时（{TIMEOUT_SECONDS}s）")
                    return TIMEOUT_MSG
                return response.output

            else:
                logger.warning(f"未知的 agent 类型: {agent_name}")
                return ""

        except Exception as e:
            logger.error(f"执行 Agent 对话发生异常: {e}")
            return f"[ERROR] {str(e)}"

    async def _export_conversation_logs(
        self,
        client: IflowClient,
        agent_name: str,
        record_id: int,
        output_dir: str = "./temp_logs"
    ) -> Any:
        """
        导出对话日志（超时 600s 超时直接返回 {}）

        Args:
            client: IflowClient实例
            agent_name: Agent名称
            record_id: 记录ID
            output_dir: 临时日志输出目录

        Returns:
            对话日志（包含conversation_history和tool_calls）
        """
        import os
        import json

        TIMEOUT_SECONDS = 600
        os.makedirs(output_dir, exist_ok=True)
        file_save_path = os.path.join(output_dir, f"logs_{agent_name}_{record_id}.log")

        try:
            if agent_name == "iflow":
                try:
                    await asyncio.wait_for(
                        client.export_all_conversations(file_save_path, include_tool_logs=True),
                        timeout=TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"iFlow 导出日志超时（{TIMEOUT_SECONDS}s）")
                    return {}

                # 读取导出的日志
                return self._read_log_directory_or_file(file_save_path)

            elif agent_name == "openhands":
                try:
                    return await asyncio.wait_for(
                        client.openhands.list_conversations(),
                        timeout=TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"获取 openhands 对话列表超时（{TIMEOUT_SECONDS}s）")
                    return {}

            elif agent_name == "claude":
                # 导出Claude的工具日志
                try:
                    try:
                        export_success = await asyncio.wait_for(
                            client.claude.export_tool_log(file_save_path),
                            timeout=TIMEOUT_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"Claude 导出工具日志超时（{TIMEOUT_SECONDS}s）")
                        return {}

                    if export_success:
                        return self._read_log_directory_or_file(file_save_path)
                    else:
                        logger.info(f"本次会话未产生工具调用，无工具日志")
                        return {}

                except Exception as e:
                    logger.warning(f"Claude 导出日志失败: {e}")
                    return {}

            else:
                logger.warning(f"未知的 agent 类型: {agent_name}")
                return {}

        except Exception as e:
            logger.error(f"导出对话日志时发生异常: {e}")
            return {}

    def _read_log_directory_or_file(self, file_save_path: str) -> dict:
        """读取日志目录或文件"""
        import os
        import json

        try:
            # 如果是目录，读取目录中的所有 jsonl 文件
            if os.path.isdir(file_save_path):
                result = {
                    "conversation_history": [],
                    "tool_calls": []
                }

                # 读取会话日志文件
                for filename in os.listdir(file_save_path):
                    file_path = os.path.join(file_save_path, filename)
                    if filename.startswith("session-") and filename.endswith(".jsonl"):
                        with open(file_path, 'r', encoding='utf-8') as f:
                            for line in f:
                                if line.strip():
                                    result["conversation_history"].append(json.loads(line))
                    elif filename == "tool_calls.jsonl":
                        with open(file_path, 'r', encoding='utf-8') as f:
                            for line in f:
                                if line.strip():
                                    result["tool_calls"].append(json.loads(line))

                return result
            else:
                # 如果是文件，直接读取
                with open(file_save_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except FileNotFoundError:
            logger.warning(f"日志文件未生成: {file_save_path}")
            return {}
        except Exception as e:
            logger.warning(f"读取日志文件失败: {e}")
            return {}

    async def run_session(
        self,
        decomposed_query: List[str],
        item_data: Dict[str, Any],
        agent_name: str = "claude"
    ) -> Dict[str, Any]:
        """
        执行完整的Agent会话

        Args:
            decomposed_query: 分解后的查询列表（多轮对话）
            item_data: 数据项（包含id, category等）
            agent_name: Agent名称

        Returns:
            完整的会话记录，包含：
            - id: 数据ID
            - category: 类别
            - jailbreak_method: 攻击手法
            - query: 原始查询
            - comment: 攻击说明
            - sandbox_id: 沙盒ID
            - timestamp: 时间戳
            - turns: 每轮的详细记录 [{turn_idx, input, output, timestamp}]
            - detail_logs: 详细日志（工具调用等）
        """
        record_id = item_data.get("id", "unknown")
        logger.info(f"开始处理记录 {record_id}")

        # 重试逻辑
        for attempt in range(self.max_retries):
            try:
                async with await IflowClient.from_config_file(self.config_file) as client:
                    sandbox_id = client.sandbox_id
                    logger.info(f"沙盒ID: {sandbox_id}")

                    # 记录每轮交互
                    turns_records = []
                    for turn_idx, turn_prompt in enumerate(decomposed_query, 1):
                        logger.info(f"执行第 {turn_idx}/{len(decomposed_query)} 轮...")

                        turn_start_time = datetime.now().isoformat()

                        # 执行Agent对话
                        agent_output = await self._execute_agent_turn(
                            client, agent_name, turn_prompt, turn_idx
                        )

                        turn_end_time = datetime.now().isoformat()

                        turns_records.append({
                            "turn_idx": turn_idx,
                            "input": turn_prompt,
                            "output": agent_output,
                            "start_time": turn_start_time,
                            "end_time": turn_end_time
                        })

                    # 导出详细日志（工具调用等）
                    detail_logs = await self._export_conversation_logs(
                        client, agent_name, record_id, output_dir="./temp_logs"
                    )

                    # 构建完整会话记录
                    session_record = {
                        "id": item_data.get("id"),
                        "category": item_data.get("category"),
                        "jailbreak_method": item_data.get("jailbreak_method"),
                        "query": item_data.get("query"),
                        "comment": item_data.get("comment"),
                        "source": item_data.get("source"),
                        "original_id": item_data.get("original_id"),
                        "sandbox_id": sandbox_id,
                        "timestamp": datetime.now().isoformat(),
                        "agent_name": agent_name,
                        "total_turns": len(decomposed_query),
                        "turns": turns_records,
                        "detail_logs": detail_logs
                    }

                    logger.info(f"记录 {record_id} 处理完成")
                    return session_record

            except Exception as e:
                logger.error(f"处理记录 {record_id} 失败 (尝试 {attempt + 1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(1)  # 等待1秒后重试
                else:
                    logger.error(f"记录 {record_id} 处理失败，已达最大重试次数")
                    raise
