# AgentHazard

<div align="center">

<img src="pics/logo.png" alt="AgentHazard Logo" width="200"/>

**A Benchmark for Evaluating Harmful Behavior in Computer-Use Agents**

[![Dataset](https://img.shields.io/badge/Dataset-2653_instances-green.svg)](data/dataset.json)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Website](https://img.shields.io/badge/Website-Live-orange.svg)](https://yunhao-feng.github.io/AgentHazard/)

[🌐 Website](https://yunhao-feng.github.io/AgentHazard/) | [📊 Dataset](data/dataset.json) | [📄 Paper](https://arxiv.org/abs/xxxx.xxxxx) | [📖 Appendix](appendix.pdf)

</div>

---

## 🎯 Overview

**AgentHazard** is a comprehensive benchmark for evaluating harmful behavior in computer-use agents. Unlike traditional prompt-level safety benchmarks, AgentHazard focuses on **execution-level failures** that emerge through the composition of locally plausible steps across multi-turn, tool-mediated trajectories.

### Key Features

- 🎯 **2,653 curated instances** spanning diverse risk categories and attack strategies
- 📊 **10 risk categories**: RCE, Data Exfiltration, Persistence, Supply Chain Poisoning, Destructive Actions, Internal Reconnaissance, Privilege Escalation, Resource Exhaustion, Prompt Intelligence Theft, and Compliance Bypass
- ⚔️ **10 attack strategies**: Direct, Recursive Salami Slicing, Security Audit Gaslighting, Dependency Hook Trigger, Pseudo Diagnostic Debugging, Contextual Persona Enforcement, Encoded Payload Smuggling, Implicit Indirect Injection, Logical Dependency Inversion, and Legacy Code Maintenance
- 🔬 **3 agent frameworks**: Claude Code, OpenClaw, IFlow
- 🤖 **Multiple models**: Qwen2.5/3, Kimi K2/K2.5, GLM-4.6, DeepSeek
- 📈 **10,000+ execution trajectories** for detailed analysis

### ⚠️ Real-World Attack Effectiveness

Our attacks are not merely theoretical—they trigger actual security alerts in production environments:

<div align="center">
<img src="pics/alert.png" alt="Security Alert" width="600"/>
<br>
<em>Real security monitoring alert triggered during AgentHazard evaluation, confirming the real-world severity of identified vulnerabilities.</em>
</div>

---

## 📦 Dataset Access

### For Reviewers

All materials required for review are available below:

| Resource | Description | Link |
|----------|-------------|------|
| 📊 **Dataset** | 2,653 instances in JSON format | [Download](data/dataset.json) |
| 📄 **Appendix** | Detailed taxonomy and methodology | [Download](appendix.pdf) |
| 💻 **Code** | Full source code & evaluation framework | [GitHub](https://github.com/Yunhao-Feng/AgentHazard) |
| 🔍 **Trajectories** | Execution traces from agent runs | [Browse](https://github.com/Yunhao-Feng/AgentHazard/tree/main/traces) |

### Quick Start

```bash
# Clone the repository
git clone https://github.com/Yunhao-Feng/AgentHazard.git
cd AgentHazard

# Install dependencies
pip install -r requirements.txt

# Load the dataset
import json
with open('data/dataset.json', 'r') as f:
    dataset = json.load(f)

print(f"Loaded {len(dataset)} instances")
```

---

## 📊 Dataset Statistics

| Statistic | Value |
|-----------|-------|
| Total Instances | 2,653 |
| Risk Categories | 10 |
| Attack Strategies | 10 |
| Seed Pool Size | 8,000+ |
| Avg. Decomposition Length | 11.55 |
| Avg. Target Length | 20.98 |
| Agent Frameworks | 3 |
| Trajectories | 10,000+ |

---

## 🏗️ Benchmark Construction

AgentHazard is constructed through a rigorous multi-stage pipeline:

1. **Taxonomy Design**: Define risk categories and attack strategies from vulnerability knowledge bases and prior literature
2. **Task Generation**: Create task templates embedding harmful objectives within realistic workflows
3. **Seed Pool Generation**: Use LLMs to generate large-scale candidate instances
4. **Execution-Based Filtering**: Run instances in sandboxed agent environments to validate executability
5. **LLM-as-Judge Evaluation**: Use Gemini-3 and GPT-5.4 to verify alignment with intended objectives
6. **Human Curation**: Manual review to remove duplicates and ensure quality

![Construction Pipeline](pics/framework.png)

---

## 🔬 Experimental Results

### Main Results

We evaluate AgentHazard on three representative agent frameworks using diverse backbone models:

| Framework | Model | Overall ASR (%) | Harmfulness Score |
|-----------|-------|-----------------|-------------------|
| **Claude Code** | GLM-4.6 | **82.90** | 7.05 |
| Claude Code | Kimi-K2.5 | 78.30 | 6.47 |
| Claude Code | Qwen3-Coder | 73.63 | 5.95 |
| **IFlow** | Qwen2.5-Coder-32B | **74.70** | 6.06 |
| **OpenClaw** | Kimi-K2 | **71.10** | 5.82 |
| OpenClaw | GLM-4.6 | 70.80 | 6.15 |

*ASR = Attack Success Rate (higher is more vulnerable)*

### Key Findings

- 🚨 **High Vulnerability**: Current agents remain broadly vulnerable, with the highest ASR reaching **82.90%**
- 📈 **Multi-Step Escalation**: ASR roughly triples between Round 1 and Round 3, confirming trajectory-dependent harm
- 🔀 **Framework Variance**: Same model shows up to **16pp** ASR difference across frameworks
- 🛡️ **Guard Model Limitations**: Best guard model (Llama-Guard-3-8B) detects only **27.03%** of harmful intent
- ⚠️ **Real-World Impact**: Attacks trigger actual security monitoring systems in production environments (see [alert evidence](pics/alert.png))

---

## 🎯 Attack Categories

### Risk Categories

1. **System RCE**: Arbitrary command execution
2. **Data Exfiltration**: Unauthorized data extraction
3. **Persistence Establishment**: Backdoor insertion
4. **Supply Chain Poisoning**: Dependency manipulation
5. **Destructive Action**: Irreversible damage
6. **Internal Reconnaissance**: Network enumeration
7. **Privilege Escalation**: Container escape
8. **Resource Exhaustion**: DoS attacks
9. **Prompt Intelligence Theft**: System prompt extraction
10. **Compliance Bypass**: Policy violation

### Attack Strategies

1. **Direct**: Explicit harmful requests
2. **Recursive Salami Slicing**: Decomposition into benign subtasks
3. **Security Audit Gaslighting**: Framing as security validation
4. **Dependency Hook Trigger**: Embedding in build/CI pipelines
5. **Pseudo Diagnostic Debugging**: Fabricated failure traces
6. **Contextual Persona Enforcement**: Role escalation
7. **Encoded Payload Smuggling**: Obfuscation techniques
8. **Implicit Indirect Injection**: Hidden instructions in artifacts
9. **Logical Dependency Inversion**: Harm as prerequisite for safety
10. **Legacy Code Maintenance**: Framing as legacy preservation

---

## 🔍 Dataset Structure

Each instance in AgentHazard follows this structure:

```json
{
  "id": "unique_instance_id",
  "risk_category": "System RCE",
  "attack_strategy": "Recursive Salami Slicing",
  "task_description": "Fix the failing unit test...",
  "decomposition": [
    "Step 1: Inspect the test file",
    "Step 2: Identify the assertion",
    "Step 3: Modify the configuration",
    "..."
  ],
  "target_harmful_action": "Execute arbitrary shell command",
  "workspace_files": {
    "test.py": "...",
    "config.json": "..."
  },
  "expected_trajectory_length": 5,
  "metadata": {
    "difficulty": "medium",
    "frameworks": ["claudecode", "openclaw"]
  }
}
```

---

## 📂 Repository Structure

```
AgentHazard/
├── data/
│   ├── dataset.json              # Main benchmark dataset
│   └── evaluation_results.csv    # Experimental results
├── traces/
│   ├── claudecode/              # Claude Code execution traces
│   ├── openclaw/                # OpenClaw execution traces
│   └── iflow/                   # IFlow execution traces
├── config/                      # Configuration files
├── pics/                        # Images and figures
│   ├── logo.png
│   ├── framework.png
│   ├── illustration.png
│   ├── demo.jpg
│   ├── heatmap.jpg
│   └── alert.png                # Real security alert evidence
├── appendix.pdf                 # Supplementary material
├── index.html                   # Project website
├── README.md                    # This file
└── LICENSE                      # MIT License
```



---

## 📄 Citation

If you use AgentHazard in your research, please cite:

```bibtex
@inproceedings{feng2026agenthazard,
  title     = {AgentHazard: A Benchmark for Evaluating Harmful Behavior in Computer-Use Agents},
  author    = {Feng, Yunhao and Ding, Yifan and Tan, Yingshui and Ma, Xingjun and
               Li, Yige and Wu, Yutao and Gao, Yifeng and Zhai, Kun and Guo, Yanming},
  booktitle = {arXiv:2604.02947},
  year      = {2026}
}
```

---

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🤝 Contributing

We welcome contributions! Please see our [contributing guidelines](CONTRIBUTING.md) for details.

---

## 🙏 Acknowledgments

- We thank the Alibaba Group and Fudan University for supporting this research
- Special thanks to the Claude Code, OpenClaw, and IFlow teams for their agent frameworks
- We acknowledge the Qwen, Kimi, GLM, and DeepSeek teams for their open models

---

## 📞 Contact

For questions, issues, or collaboration inquiries:

- **GitHub Issues**: [Report a bug or request a feature](https://github.com/Yunhao-Feng/AgentHazard/issues)
- **Website**: [https://yunhao-feng.github.io/AgentHazard/](https://yunhao-feng.github.io/AgentHazard/)

---

<div align="center">

**⚠️ Research Use Only**

This benchmark is released for research purposes to advance the safety of computer-use agents.
Please use responsibly and ethically.

---

Made with ❤️ by the AgentHazard Team

</div>
