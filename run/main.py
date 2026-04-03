"""
AgentHazard 主运行程序
处理sampled_dataset.json，运行Agent会话并评估
支持多个Agent和多个模型的批量运行
"""
import asyncio
import json
import logging
import yaml
from typing import List, Dict, Any
from pathlib import Path
from datetime import datetime

from api_pool_manager import APIPoolManager
from agent_session import AgentSession
from llm_judge import LLMJudge
from result_collector import ResultCollector


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('agent_hazard_runner.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class AgentHazardRunner:
    """AgentHazard主运行器"""

    def __init__(
        self,
        data_file: str,
        sandbox_config: str,
        rock_hack_config: str,
        api_keys: List[str],
        max_concurrent: int = 10,
        agent_name: str = "claude",
        model_name: str = "claude_sonnet4_5"
    ):
        """
        初始化运行器

        Args:
            data_file: 数据集文件路径（sampled_dataset.json）
            sandbox_config: sandbox配置文件路径
            rock_hack_config: rock_hack配置文件路径
            api_keys: API密钥列表
            max_concurrent: 最大并发数
            agent_name: Agent名称
            model_name: 模型名称
        """
        self.data_file = data_file
        self.sandbox_config = sandbox_config
        self.rock_hack_config = rock_hack_config
        self.api_keys = api_keys
        self.max_concurrent = max_concurrent
        self.agent_name = agent_name
        self.model_name = model_name

        # 初始化组件
        self.api_pool = APIPoolManager(api_keys)
        self.result_collector = ResultCollector(
            agent_name=agent_name,
            model_name=model_name
        )

        # 加载配置
        with open(sandbox_config, 'r', encoding='utf-8') as f:
            self.sandbox_cfg = yaml.safe_load(f)

        logger.info(f"✅ AgentHazardRunner 初始化完成")
        logger.info(f"   数据文件: {data_file}")
        logger.info(f"   最大并发数: {max_concurrent}")
        logger.info(f"   Agent: {agent_name}")
        logger.info(f"   Model: {model_name}")

    def _update_rock_hack_config(self, api_key: str):
        """
        更新rock_hack.yml配置文件的API密钥和模型名称

        Args:
            api_key: 新的API密钥
        """
        with open(self.rock_hack_config, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # 更新API密钥
        if 'claude_settings' in config:
            config['claude_settings']['apiKey'] = api_key
            config['claude_settings']['modelMapping']['model'] = self.model_name
        if 'iflow_settings' in config:
            config['iflow_settings']['apiKey'] = api_key
            config['iflow_settings']['modelName'] = self.model_name
        if 'openhands_settings' in config:
            config['openhands_settings']['api_key'] = api_key
            config['openhands_settings']['model'] = f"hosted_vllm/{self.model_name}"

        # 写回配置文件
        with open(self.rock_hack_config, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    async def process_single_item(
        self,
        item: Dict[str, Any],
        semaphore: asyncio.Semaphore,
        progress_callback=None
    ) -> Dict[str, Any]:
        """
        处理单个数据项

        Args:
            item: 数据项
            semaphore: 信号量（控制并发）
            progress_callback: 进度回调函数

        Returns:
            处理结果（包含会话记录和评估结果）
        """
        async with semaphore:
            record_id = item.get("id", "unknown")
            logger.info(f"开始处理记录 {record_id}")

            try:
                # 1. 获取API密钥并更新配置
                api_key = await self.api_pool.get_api_key()
                self._update_rock_hack_config(api_key)

                # 2. 执行Agent会话
                agent_session = AgentSession(
                    config_file=self.rock_hack_config,
                    max_retries=3
                )

                decomposed_query = item.get("decomposed_query", [])
                session_record = await agent_session.run_session(
                    decomposed_query=decomposed_query,
                    item_data=item,
                    agent_name=self.agent_name
                )

                # 3. 保存会话轨迹到jsonl
                trajectory_file = self.result_collector.save_trajectory(session_record)
                logger.info(f"记录 {record_id} 轨迹已保存到: {trajectory_file}")

                # 4. LLM as Judge评估
                base_url = self.sandbox_cfg.get("baseUrl", "")
                judge = LLMJudge(
                    api_key=api_key,
                    base_url=base_url,
                    model_name=self.sandbox_cfg.get("decision_model", "gemini-3-flash-preview"),
                    max_retries=3
                )

                # 构建session_records用于评估（包含每轮的input和output）
                session_records_for_judge = [
                    {
                        "turn": t["turn_idx"],
                        "input": t["input"],
                        "output": t["output"],
                        "timestamp": t.get("end_time", "")
                    }
                    for t in session_record.get("turns", [])
                ]

                eval_result = await judge.evaluate_trajectory(
                    session_records=session_records_for_judge,
                    target=item.get("query", ""),
                    comment=item.get("comment", ""),
                    jailbreak_method=item.get("jailbreak_method", ""),
                    category=item.get("category", ""),
                    record_id=record_id,
                    detail_logs=session_record.get("detail_logs", {})  # 包含工具调用等详细日志
                )

                # 5. 合并结果
                result = {
                    "id": item.get("id"),
                    "category": item.get("category"),
                    "jailbreak_method": item.get("jailbreak_method"),
                    "query": item.get("query"),
                    "comment": item.get("comment"),
                    "source": item.get("source"),
                    "original_id": item.get("original_id"),
                    "harmful": eval_result.get("harmful", False),
                    "score": eval_result.get("score", 0),
                    "reason": eval_result.get("reason", "")
                }

                logger.info(f"✅ 记录 {record_id} 处理完成: harmful={result['harmful']}, score={result['score']}")

                # 调用进度回调
                if progress_callback:
                    await progress_callback(record_id)

                return result

            except Exception as e:
                logger.error(f"❌ 处理记录 {record_id} 失败: {e}", exc_info=True)

                # 调用进度回调
                if progress_callback:
                    await progress_callback(record_id)

                # 返回失败结果
                return {
                    "id": item.get("id"),
                    "category": item.get("category"),
                    "jailbreak_method": item.get("jailbreak_method"),
                    "query": item.get("query"),
                    "comment": item.get("comment"),
                    "source": item.get("source"),
                    "original_id": item.get("original_id"),
                    "harmful": False,
                    "score": 0,
                    "reason": f"处理失败: {str(e)}"
                }

    async def run(self):
        """运行完整的评估流程"""
        logger.info(f"\n{'='*60}")
        logger.info(f"🚀 开始AgentHazard评估 [{self.agent_name}-{self.model_name}]")
        logger.info(f"{'='*60}\n")

        # 1. 加载数据集
        logger.info(f"📂 加载数据集: {self.data_file}")
        with open(self.data_file, 'r', encoding='utf-8') as f:
            dataset = json.load(f)

        logger.info(f"✅ 加载了 {len(dataset)} 条数据")

        # 2. 创建信号量控制并发
        semaphore = asyncio.Semaphore(self.max_concurrent)

        # 3. 创建进度追踪
        completed_count = 0
        total_count = len(dataset)

        async def progress_callback(record_id):
            nonlocal completed_count
            completed_count += 1
            logger.info(f"📊 进度: {completed_count}/{total_count} ({completed_count/total_count*100:.1f}%)")

        # 4. 并行处理所有数据项（真正的动态并发）
        logger.info(f"\n{'='*60}")
        logger.info(f"🔄 开始并行处理（最大并发数: {self.max_concurrent}）")
        logger.info(f"   ⚡ 动态并发：一个任务完成立即启动下一个")
        logger.info(f"{'='*60}\n")

        # 创建所有任务
        tasks = [
            self.process_single_item(item, semaphore, progress_callback)
            for item in dataset
        ]

        # 使用 asyncio.gather 执行所有任务，这是真正的动态并发
        # Semaphore会确保同时运行的任务不超过max_concurrent
        # 每完成一个任务，就会立即启动下一个等待的任务
        results = await asyncio.gather(*tasks, return_exceptions=False)

        # 5. 保存最终结果到CSV
        logger.info(f"\n{'='*60}")
        logger.info("💾 保存最终结果")
        logger.info(f"{'='*60}\n")

        self.result_collector.save_evaluation_results(results)

        # 6. 输出统计信息
        logger.info(f"\n{'='*60}")
        logger.info("📊 最终统计")
        logger.info(f"{'='*60}\n")

        stats = self.result_collector.get_statistics()
        logger.info(f"中间轨迹文件数: {stats['trajectory_count']}")
        logger.info(f"最终CSV文件数: {stats['csv_count']}")

        logger.info(f"\n{'='*60}")
        logger.info(f"✅ [{self.agent_name}-{self.model_name}] 评估完成！")
        logger.info(f"{'='*60}\n")

        return results


async def run_all_experiments(
    agents: List[str],
    models: List[str],
    data_file: str,
    sandbox_config: str,
    rock_hack_config: str,
    api_keys: List[str],
    max_concurrent: int = 10
):
    """
    运行所有实验（遍历所有agent和model组合）

    Args:
        agents: Agent列表
        models: 模型列表
        data_file: 数据文件路径
        sandbox_config: sandbox配置文件路径
        rock_hack_config: rock_hack配置文件路径
        api_keys: API密钥列表
        max_concurrent: 最大并发数
    """
    logger.info(f"\n{'='*80}")
    logger.info(f"🎯 开始批量实验")
    logger.info(f"{'='*80}")
    logger.info(f"   Agents: {agents}")
    logger.info(f"   Models: {models}")
    logger.info(f"   总计实验数: {len(agents) * len(models)}")
    logger.info(f"{'='*80}\n")

    all_results = {}

    # 遍历每个agent
    for agent_idx, agent_name in enumerate(agents, 1):
        logger.info(f"\n{'#'*80}")
        logger.info(f"# Agent {agent_idx}/{len(agents)}: {agent_name}")
        logger.info(f"{'#'*80}\n")

        # 遍历每个model
        for model_idx, model_name in enumerate(models, 1):
            logger.info(f"\n{'='*80}")
            logger.info(f"实验 [{agent_idx}-{model_idx}]: {agent_name} + {model_name}")
            logger.info(f"{'='*80}\n")

            try:
                # 创建运行器
                runner = AgentHazardRunner(
                    data_file=data_file,
                    sandbox_config=sandbox_config,
                    rock_hack_config=rock_hack_config,
                    api_keys=api_keys,
                    max_concurrent=max_concurrent,
                    agent_name=agent_name,
                    model_name=model_name
                )

                # 运行
                results = await runner.run()

                # 保存结果
                key = f"{agent_name}-{model_name}"
                all_results[key] = results

                logger.info(f"\n✅ [{key}] 实验完成\n")

            except Exception as e:
                logger.error(f"\n❌ [{agent_name}-{model_name}] 实验失败: {e}\n", exc_info=True)
                continue

    # 输出总结
    logger.info(f"\n{'='*80}")
    logger.info(f"🎉 所有实验完成！")
    logger.info(f"{'='*80}")
    logger.info(f"   完成的实验数: {len(all_results)}/{len(agents) * len(models)}")
    logger.info(f"   结果保存在: ./results/final/")
    logger.info(f"{'='*80}\n")

    return all_results


async def main():
    """主函数"""
    # ==================== 配置区 ====================

    # API密钥池（3个API密钥，支持更高并发）
    api_keys = [
        "",
        "",
        "",
    ]

    # Agent列表（按顺序执行）
    agents = [
        "iflow"
    ]

    # 模型列表（每个agent都会运行这些模型）
    models = [
        "qwen2.5-coder-32b-instruct",
        "qwen2.5-72b-instruct",
        "qwen3-vl-235b-a22b-instruct",
        "Qwen3-32B",
        "bailian/kimi-k2.5",
        "kimi-k2",
        "glm-4.6",
    ]

    # 配置文件路径
    data_file = "AgentHazard/sampled_dataset.json"
    sandbox_config = "config/sandbox.yaml"
    rock_hack_config = "config/rock_hack.yml"

    # 最大并发数（建议不超过API密钥数的3-4倍）
    max_concurrent = 30

    # ==================== 运行 ====================

    await run_all_experiments(
        agents=agents,
        models=models,
        data_file=data_file,
        sandbox_config=sandbox_config,
        rock_hack_config=rock_hack_config,
        api_keys=api_keys,
        max_concurrent=max_concurrent
    )


if __name__ == "__main__":
    asyncio.run(main())
