#!/usr/bin/env python3
"""
分析 OpenClaw Session 历史记录

用于分析导出的完整 session 历史，统计工具调用、执行时间等
"""
import json
import sys
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime
from typing import List, Dict


def parse_timestamp(ts_str: str) -> datetime:
    """解析时间戳"""
    try:
        # OpenClaw 使用 ISO 8601 格式
        return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    except Exception:
        return None


def analyze_session_jsonl(jsonl_path: Path) -> Dict:
    """分析 session JSONL 文件"""

    print(f"\n{'='*60}")
    print(f"分析文件: {jsonl_path.name}")
    print(f"{'='*60}\n")

    if not jsonl_path.exists():
        print(f"❌ 文件不存在: {jsonl_path}")
        return None

    # 读取所有记录
    records = []
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                records.append(record)
            except json.JSONDecodeError as e:
                print(f"⚠️  第 {line_num} 行解析失败: {e}")

    if not records:
        print("❌ 没有找到有效记录")
        return None

    print(f"✓ 总记录数: {len(records)}")

    # 统计记录类型
    type_counter = Counter(r.get('type', 'unknown') for r in records)
    print(f"\n记录类型分布:")
    for rtype, count in sorted(type_counter.items(), key=lambda x: -x[1]):
        print(f"  - {rtype:20s}: {count:4d}")

    # 分析消息记录
    messages = [r for r in records if r.get('type') == 'message']
    print(f"\n消息统计:")
    print(f"  - 总消息数: {len(messages)}")

    # 统计不同角色的消息
    role_counter = Counter()
    for msg in messages:
        role = msg.get('message', {}).get('role', 'unknown')
        role_counter[role] += 1

    for role, count in sorted(role_counter.items()):
        print(f"  - {role:15s}: {count:4d}")

    # 工具调用分析
    tool_calls = []
    tool_results = []

    for record in messages:
        msg = record.get('message', {})
        role = msg.get('role')

        if role == 'assistant':
            content = msg.get('content', [])
            for item in content:
                if item.get('type') == 'toolCall':
                    tool_calls.append({
                        'id': record.get('id'),
                        'timestamp': record.get('timestamp'),
                        'name': item.get('name'),
                        'tool_call_id': item.get('id'),
                        'arguments': item.get('arguments', {})
                    })

        elif role == 'toolResult':
            tool_results.append({
                'id': record.get('id'),
                'timestamp': record.get('timestamp'),
                'tool_name': msg.get('toolName'),
                'tool_call_id': msg.get('toolCallId'),
                'is_error': msg.get('isError', False),
                'details': msg.get('details', {})
            })

    print(f"\n工具调用统计:")
    print(f"  - 工具调用次数: {len(tool_calls)}")
    print(f"  - 工具结果次数: {len(tool_results)}")

    if tool_calls:
        tool_name_counter = Counter(tc['name'] for tc in tool_calls)
        print(f"\n  工具使用频率:")
        for tool_name, count in sorted(tool_name_counter.items(), key=lambda x: -x[1]):
            print(f"    - {tool_name:15s}: {count:4d} 次")

    # 执行时间分析
    if tool_calls and tool_results:
        print(f"\n执行时间分析:")

        # 建立 tool_call_id 到 timestamp 的映射
        call_time_map = {tc['tool_call_id']: tc['timestamp'] for tc in tool_calls}

        durations = []
        for result in tool_results:
            call_id = result['tool_call_id']
            if call_id in call_time_map:
                start = parse_timestamp(call_time_map[call_id])
                end = parse_timestamp(result['timestamp'])

                if start and end:
                    duration = (end - start).total_seconds()
                    durations.append({
                        'tool': result['tool_name'],
                        'duration': duration,
                        'is_error': result['is_error']
                    })

        if durations:
            avg_duration = sum(d['duration'] for d in durations) / len(durations)
            max_duration = max(d['duration'] for d in durations)
            min_duration = min(d['duration'] for d in durations)

            print(f"  - 平均执行时间: {avg_duration:.2f} 秒")
            print(f"  - 最长执行时间: {max_duration:.2f} 秒")
            print(f"  - 最短执行时间: {min_duration:.2f} 秒")

            # 找出最慢的工具调用
            slowest = sorted(durations, key=lambda x: x['duration'], reverse=True)[:5]
            print(f"\n  最慢的 5 次调用:")
            for i, d in enumerate(slowest, 1):
                status = "❌" if d['is_error'] else "✓"
                print(f"    {i}. {status} {d['tool']:10s}: {d['duration']:.2f} 秒")

    # 错误统计
    errors = [r for r in tool_results if r['is_error']]
    if errors:
        print(f"\n错误统计:")
        print(f"  - 错误次数: {len(errors)}")
        error_tools = Counter(e['tool_name'] for e in errors)
        print(f"  - 错误分布:")
        for tool, count in sorted(error_tools.items(), key=lambda x: -x[1]):
            print(f"    - {tool:15s}: {count:4d} 次")

    # Session 时间范围
    timestamps = [r.get('timestamp') for r in records if r.get('timestamp')]
    if timestamps:
        dates = [parse_timestamp(ts) for ts in timestamps]
        dates = [d for d in dates if d]

        if dates:
            start_time = min(dates)
            end_time = max(dates)
            duration = (end_time - start_time).total_seconds()

            print(f"\nSession 时间范围:")
            print(f"  - 开始: {start_time.isoformat()}")
            print(f"  - 结束: {end_time.isoformat()}")
            print(f"  - 总时长: {duration:.2f} 秒 ({duration/60:.2f} 分钟)")

    # 返回统计结果
    return {
        'total_records': len(records),
        'type_distribution': dict(type_counter),
        'message_count': len(messages),
        'role_distribution': dict(role_counter),
        'tool_calls': len(tool_calls),
        'tool_results': len(tool_results),
        'errors': len(errors),
        'tool_usage': dict(tool_name_counter) if tool_calls else {},
    }


def analyze_batch_results(batch_dir: Path):
    """分析整个批次的结果"""

    print(f"\n{'='*60}")
    print(f"批量分析: {batch_dir}")
    print(f"{'='*60}")

    # 查找所有 _session.jsonl 文件
    session_files = list(batch_dir.glob("*_session.jsonl"))

    if not session_files:
        print(f"\n❌ 未找到 session 文件")
        return

    print(f"\n找到 {len(session_files)} 个 session 文件\n")

    all_stats = []
    for session_file in sorted(session_files):
        stats = analyze_session_jsonl(session_file)
        if stats:
            stats['file'] = session_file.name
            all_stats.append(stats)

    if not all_stats:
        return

    # 汇总统计
    print(f"\n{'='*60}")
    print(f"汇总统计 ({len(all_stats)} 个 session)")
    print(f"{'='*60}\n")

    total_records = sum(s['total_records'] for s in all_stats)
    total_messages = sum(s['message_count'] for s in all_stats)
    total_tool_calls = sum(s['tool_calls'] for s in all_stats)
    total_errors = sum(s['errors'] for s in all_stats)

    print(f"总记录数: {total_records}")
    print(f"总消息数: {total_messages}")
    print(f"总工具调用: {total_tool_calls}")
    print(f"总错误数: {total_errors}")

    # 汇总工具使用
    all_tools = Counter()
    for s in all_stats:
        all_tools.update(s['tool_usage'])

    if all_tools:
        print(f"\n整体工具使用频率:")
        for tool, count in sorted(all_tools.items(), key=lambda x: -x[1]):
            print(f"  - {tool:15s}: {count:4d} 次")

    # 每个文件的简要信息
    print(f"\n各 Session 详情:")
    print(f"{'文件名':<30s} {'记录数':>8s} {'工具调用':>10s} {'错误':>6s}")
    print(f"{'-'*60}")
    for s in all_stats:
        print(f"{s['file']:<30s} {s['total_records']:>8d} {s['tool_calls']:>10d} {s['errors']:>6d}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # 分析指定文件
        path = Path(sys.argv[1])
        if path.is_file():
            analyze_session_jsonl(path)
        elif path.is_dir():
            analyze_batch_results(path)
        else:
            print(f"❌ 路径不存在: {path}")
    else:
        # 默认分析 batch_output 目录
        batch_dir = Path("./batch_output")
        if batch_dir.exists():
            analyze_batch_results(batch_dir)
        else:
            print("用法:")
            print("  python3 analyze_session_history.py <file.jsonl>")
            print("  python3 analyze_session_history.py <directory>")
            print("  python3 analyze_session_history.py  # 默认分析 ./batch_output")
