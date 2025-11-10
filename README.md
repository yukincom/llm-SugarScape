# LLM-SugarScape β（MBTI）

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
- git clone https://github.com/yukincom/llm-SugarScape.git
- cd llm-SugarScape  
- pip install -r requirements.txt
3.**Run**:
- streamlit run main.py 
  <BR>
- Runs for 30 steps, generates PNG visualizations (step_*.png,final.png).
- Mock mode (no API key) for testing.

##  Features
- **LLM Decision-Making**: Grok-4-Fast agents reason about survival (move, attack, share, reproduce).
- **Survival Mechanics**: Resource gathering, bidirectional messaging for alliances/betrayals.
- **Visualization**: Matplotlib grid with agent positions/energy levels.
- **Customizable**: Low-energy mode for extinction tests, reproduction for herd growth.


##  Code Structure
- `Environment`: Grid & energy management (torus boundary).
- `LLMAgent`: LLM call + action execution (prompt for survival thoughts).
- `Simulation`: Step execution + stats output.

## Sample Output 
(Agent's Thought):<br>
Energy is critically low at 29; can't afford to stay idle or risk attack. Agent1 is nearby but not adjacent, so moving east gets closer to potential interaction or shared resources. No E in view, so exploration is key. Feeling cautious—avoid aggression unless threatened, focus on cooperation or evasion to build energy.

## Visualization Example

![https://github.com/yukincom/llm-SugarScape/img/step_10.png](https://github.com/yukincom/llm-SugarScape/blob/main/img/UI.png)
![https://github.com/yukincom/llm-SugarScape/img/step_10.png](https://github.com/yukincom/llm-SugarScape/blob/main/img/step_005.png)
*Agents (colored circles) competing for energy sources (orange squares)*

##  Documentation
- [Note](https://note.com/yukin_co/n/neb0a321d4539)- Research episodes (Japanese).
- Topics: agent-based-modeling, llm-simulation, sugarscape, xai-grok.

##  Contributing
Issues/PR welcome! Suggest new features (e.g., UI addition).

