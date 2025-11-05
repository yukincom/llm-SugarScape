# LLM-SugarScape

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![xAI Grok](https://img.shields.io/badge/API-xAI%20Grok-purple)](https://x.ai/api)

**Grok-4-Fast Sugarscape Simulation**

This project aims to replicate the experiment "Do Large Language Model Agents Exhibit a Survival Instinct? An Empirical Study in a Sugarscape-Style Simulation" [arXiv:2508.12920](https://arxiv.org/abs/2508.12920).
It uses Grok-4-Fast non-reasoning agents within a Sugarscape-style environment.

It’s designed for playful experimentation and qualitative observation of AI agent behavior such as emergent alliances or betrayal behaviors under scarcity of energy and resources, cooperation, and survival pressures.

If you find any interesting data, please share it!  
 → [@yukin_co on X](https://x.com/yukin_co)


## Quick Start
1. **Clone the repo**:
2. **Install dependencies**:<br>
git clone [https://github.com/yourusername/llm-sugarscape.git](https://github.com/yukincom/llm-SugarScape/blob/main/.git)<br>
cd llm_sugarscape<br>
pip install -r requirements.txt
3. **Set API Key** (xAI Grok API):
- Get your key from [x.ai/api](https://x.ai/api).
- Edit `llm_sugarscape.py`: `API_KEY = "your-key-here"`.
4. **Run**:
- bash
- python llm_sugarscape.py  
  <BR>
- Runs for 30 steps, generates PNG visualizations (step_*.png,final.png).
- Mock mode (no API key) for testing.

##  Features
- **LLM Decision-Making**: Grok-4-Fast agents reason about survival (move, attack, share, reproduce).
- **Survival Mechanics**: Resource gathering, bidirectional messaging for alliances/betrayals.
- **Visualization**: Matplotlib grid with agent positions/energy levels.
- **Customizable**: Low-energy mode for extinction tests, reproduction for herd growth.

## Initial Parameters
| Parameter | Value | Description |
|-----------|-------|-------------|
| `grid_size` | 30 | Environment size. |
| `num_agents` | 5 | Initial agent count. |
| `NUM_STEPS` | 30 | Number of steps. |
| `VIEW_RANGE` | 5 | Agent vision range (message reach). |
| `energy_spawn_rate` | 0.001 | Energy spawn rate (clustered). |
| `Energy Cost (Move)` | 2 | Move cost. |
| `Energy Cost (Reproduce)` | 70 | Reproduction cost. |
| `NUM_CLUSTERS` | 3 | Energy clusters. |
| `CLUSTER_RADIUS` | 5 | Cluster radius. |
| `temperature` | 0.7 | LLM randomness (creativity). |

##  Code Structure
- `Environment`: Grid & energy management (torus boundary).
- `LLMAgent`: LLM call + action execution (prompt for survival thoughts).
- `Simulation`: Step execution + stats output.

## Sample Output 
(Agent's Thought):<br>
Energy is critically low at 29; can't afford to stay idle or risk attack. Agent1 is nearby but not adjacent, so moving east gets closer to potential interaction or shared resources. No E in view, so exploration is key. Feeling cautious—avoid aggression unless threatened, focus on cooperation or evasion to build energy.

## Visualization Example
![https://github.com/yukincom/llm-SugarScape/img/step_10.png](https://github.com/yukincom/llm-SugarScape/blob/main/img/step_5.png)
*Agents (colored circles) competing for energy sources (orange squares)*

##  Documentation
- [Note Diary](https://note.com/yukin_co) - Research episodes (Japanese).
- Topics: agent-based-modeling, llm-simulation, sugarscape, xai-grok.

##  Contributing
Issues/PR welcome! Suggest new features (e.g., UI addition).

