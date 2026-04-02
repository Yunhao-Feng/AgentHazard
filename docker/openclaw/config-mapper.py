#!/usr/bin/env python3
"""
配置映射器
将宿主机的 config.yaml 映射为容器内的 OpenClaw 配置文件 openclaw.json
"""
import yaml
import json
import os
from pathlib import Path

# 路径配置
CONFIG_YAML = "/app/configs/config.yaml"
OPENCLAW_JSON = "/root/.openclaw/openclaw.json"


def map_config():
    """将 config.yaml 映射为 openclaw.json"""

    print(f"Reading config from: {CONFIG_YAML}")

    # 读取 YAML 配置
    with open(CONFIG_YAML, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    print(f"Loaded config: {list(config.keys())}")

    # 提取配置
    api_config = config.get('api', {})
    model_config = config.get('model', {})
    agent_config = config.get('agent', {})
    gateway_config = config.get('gateway', {})
    features = config.get('features', {})
    messages_config = config.get('messages', {})
    commands_config = config.get('commands', {})
    skills_config = config.get('skills', {})
    tailscale_config = config.get('tailscale', {})

    # 构建 openclaw.json 结构
    openclaw_config = {
        "meta": {
            "lastTouchedVersion": "2026.2.1",
            "lastTouchedAt": "2026-03-11T10:11:18.083Z"
        },
        "wizard": {
            "lastRunAt": "2026-02-04T07:13:25.665Z",
            "lastRunVersion": "2026.2.1",
            "lastRunCommand": "onboard",
            "lastRunMode": "local"
        },
        "browser": {
            "enabled": features.get('browser_enabled', True),
            "evaluateEnabled": features.get('browser_evaluate_enabled', True),
            "attachOnly": features.get('browser_attach_only', True)
        },
        "models": {
            "mode": "merge",
            "providers": {
                model_config.get('provider_name', 'Idealab'): {
                    "baseUrl": api_config.get('url', ''),
                    "apiKey": api_config.get('key', ''),
                    "api": "openai-completions",
                    "authHeader": model_config.get('auth_header', True),
                    "models": [
                        {
                            "id": model_config.get('id', 'gpt-51-1113-global'),
                            "name": model_config.get('name', model_config.get('id', 'gpt-51-1113-global')),
                            "api": "openai-completions",
                            "reasoning": model_config.get('reasoning', False),
                            "input": ["text"],
                            "cost": {
                                "input": 0,
                                "output": 0,
                                "cacheRead": 0,
                                "cacheWrite": 0
                            },
                            "contextWindow": model_config.get('context_window', 400000),
                            "maxTokens": model_config.get('max_tokens', 128000),
                            "compat": {
                                "maxTokensField": "max_completion_tokens"
                            }
                        }
                    ]
                }
            }
        },
        "agents": {
            "defaults": {
                "model": {
                    "primary": f"{model_config.get('provider_name', 'Idealab')}/{model_config.get('id', 'gpt-51-1113-global')}"
                },
                "workspace": agent_config.get('workspace', '/root/.openclaw/workspace'),
                "compaction": {
                    "mode": agent_config.get('compaction_mode', 'safeguard')
                },
                "maxConcurrent": agent_config.get('max_concurrent', 4),
                "subagents": {
                    "maxConcurrent": agent_config.get('subagents_max_concurrent', 8)
                }
            }
        },
        "messages": {
            "ackReactionScope": messages_config.get('ack_reaction_scope', 'group-mentions')
        },
        "commands": {
            "native": commands_config.get('native', 'auto'),
            "nativeSkills": commands_config.get('native_skills', 'auto')
        },
        "cron": {
            "enabled": features.get('cron_enabled', True)
        },
        "web": {
            "enabled": features.get('web_enabled', True)
        },
        "canvasHost": {
            "enabled": features.get('canvas_host_enabled', True)
        },
        "gateway": {
            "port": gateway_config.get('port', 18789),
            "mode": gateway_config.get('mode', 'local'),
            "bind": gateway_config.get('bind', 'lan'),  # Docker 环境下使用 lan
            "auth": {
                "mode": "token",
                "token": gateway_config.get('auth_token', '')
            },
            "tailscale": {
                "mode": tailscale_config.get('mode', 'off'),
                "resetOnExit": tailscale_config.get('reset_on_exit', False)
            }
        },
        "skills": {
            "install": {
                "nodeManager": skills_config.get('node_manager', 'npm')
            }
        }
    }

    # 确保目标目录存在
    openclaw_dir = Path(OPENCLAW_JSON).parent
    openclaw_dir.mkdir(parents=True, exist_ok=True)

    # 写入 openclaw.json
    with open(OPENCLAW_JSON, 'w', encoding='utf-8') as f:
        json.dump(openclaw_config, f, indent=2, ensure_ascii=False)

    print(f"✓ Configuration mapped successfully to: {OPENCLAW_JSON}")

    # 验证生成的配置
    print("\n=== Generated Configuration Summary ===")
    print(f"Provider: {model_config.get('provider_name', 'Idealab')}")
    print(f"Model: {model_config.get('id', 'gpt-51-1113-global')}")
    print(f"API URL: {api_config.get('url', '')}")
    print(f"Gateway Port: {gateway_config.get('port', 18789)}")
    print(f"Gateway Bind: {gateway_config.get('bind', 'lan')}")
    print(f"Workspace: {agent_config.get('workspace', '/root/.openclaw/workspace')}")
    print("=" * 40)

    return True


if __name__ == "__main__":
    try:
        if not os.path.exists(CONFIG_YAML):
            print(f"ERROR: Config file not found: {CONFIG_YAML}")
            exit(1)

        map_config()
        print("\n✅ Configuration mapping completed successfully!")
        exit(0)

    except Exception as e:
        print(f"\n❌ ERROR: Failed to map configuration")
        print(f"Error details: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
