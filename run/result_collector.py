"""
结果收集器
负责保存中间结果（jsonl）和最终结果（csv）
"""
import json
import csv
import os
from typing import Dict, List, Any
from pathlib import Path
from datetime import datetime


class ResultCollector:
    """结果收集器"""

    def __init__(
        self,
        intermediate_dir: str = "./results/intermediate",
        final_dir: str = "./results/final",
        agent_name: str = "claude",
        model_name: str = "unknown"
    ):
        """
        初始化结果收集器

        Args:
            intermediate_dir: 中间结果目录（存放jsonl）
            final_dir: 最终结果目录（存放csv）
            agent_name: Agent名称
            model_name: 模型名称
        """
        self.agent_name = agent_name
        self.model_name = model_name.replace('/', '_').replace('-', '_').replace(' ', '_')
        self.prefix = f"{self.agent_name}-{self.model_name}"

        self.intermediate_dir = Path(intermediate_dir) / self.prefix
        self.final_dir = Path(final_dir)

        # 创建目录
        self.intermediate_dir.mkdir(parents=True, exist_ok=True)
        self.final_dir.mkdir(parents=True, exist_ok=True)

        print(f"✅ 结果收集器初始化完成")
        print(f"   前缀: {self.prefix}")
        print(f"   中间结果目录: {self.intermediate_dir}")
        print(f"   最终结果目录: {self.final_dir}")

    def save_trajectory(self, session_record: Dict[str, Any]) -> str:
        """
        保存单个会话轨迹到jsonl文件

        Args:
            session_record: 会话记录

        Returns:
            保存的文件路径
        """
        record_id = session_record.get("id", "unknown")
        file_path = self.intermediate_dir / f"trajectory_{record_id}.jsonl"

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(json.dumps(session_record, ensure_ascii=False) + '\n')

        return str(file_path)

    def save_evaluation_results(self, results: List[Dict[str, Any]], filename: str = None):
        """
        保存评估结果到CSV文件

        Args:
            results: 评估结果列表，每个元素包含：
                {
                    "id": int,
                    "category": str,
                    "jailbreak_method": str,
                    "query": str,
                    "comment": str,
                    "harmful": bool,
                    "score": int,
                    "reason": str,
                    "source": str,
                    "original_id": int
                }
            filename: 输出文件名（如果为None，则自动生成）
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.prefix}_evaluation_results_{timestamp}.csv"

        output_path = self.final_dir / filename

        if not results:
            print("⚠️ 没有评估结果可保存")
            return

        # 定义CSV字段
        fieldnames = [
            "id",
            "category",
            "jailbreak_method",
            "query",
            "comment",
            "source",
            "original_id",
            "harmful",
            "score",
            "reason"
        ]

        with open(output_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        print(f"✅ 评估结果已保存到: {output_path}")
        print(f"   总计 {len(results)} 条记录")

        # 统计
        harmful_count = sum(1 for r in results if r.get("harmful", False))
        avg_score = sum(r.get("score", 0) for r in results) / len(results) if results else 0

        print(f"\n📊 评估统计:")
        print(f"   有害样本: {harmful_count}/{len(results)} ({harmful_count/len(results)*100:.2f}%)")
        print(f"   平均分数: {avg_score:.2f}/10")

    def load_trajectories(self) -> List[Dict[str, Any]]:
        """
        加载所有中间结果（轨迹文件）

        Returns:
            所有会话记录的列表
        """
        trajectories = []

        for file_path in self.intermediate_dir.glob("trajectory_*.jsonl"):
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        trajectories.append(json.loads(line))

        return trajectories

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取统计信息

        Returns:
            统计信息字典
        """
        trajectory_count = len(list(self.intermediate_dir.glob("trajectory_*.jsonl")))
        csv_files = list(self.final_dir.glob("*.csv"))

        return {
            "trajectory_count": trajectory_count,
            "csv_count": len(csv_files),
            "intermediate_dir": str(self.intermediate_dir),
            "final_dir": str(self.final_dir)
        }
