"""One emoji snapshot renderer for the live board, history and saved images."""

from collections import defaultdict
from functools import lru_cache
import math
import threading

from matplotlib.figure import Figure
from matplotlib.image import imread
from matplotlib.offsetbox import AnnotationBbox, OffsetImage

from agent_view import agent_states, attack_victims, icon_path

PLOT_LOCK = threading.RLock()


@lru_cache(maxsize=None)
def icon_pixels(state):
    return imread(icon_path(state))


def add_icon(ax, state, point, size, gid, zorder=4, offset=(0, 0)):
    marker = AnnotationBbox(OffsetImage(icon_pixels(state), zoom=size / 72), point,
                            xybox=offset, boxcoords="offset points", frameon=False,
                            pad=0, zorder=zorder)
    marker.set_gid(gid)
    ax.add_artist(marker)
    return marker


def draw_grid(snapshot, grid_size, reproduce_cost):
    """Render only recorded state; never advance the simulation or its RNG.

    reproduce_cost is retained in the renderer's existing call signature;
    facial expressions use the user-selected fixed health thresholds 50/150.
    """
    fig = Figure(figsize=(7.4, 7.4), dpi=110, facecolor="white")
    ax = fig.subplots()
    ax.set_facecolor("#fffdf7")
    # The timeline places the board beside dialogue. Keep faces recognizable
    # after the figure is scaled into that narrower column.
    size = min(34, max(16, 800 / grid_size))
    for index, food in enumerate(snapshot["environment"].get("resources", [])):
        add_icon(ax, "resource", (food["x"], food["y"]), size * 0.88, f"food-{index}", zorder=2)

    events = {event["agent_id"]: event for event in snapshot.get("events", [])}
    victims = attack_victims(events.values())
    cells = defaultdict(list)
    for agent in snapshot["agents"]:
        # Show death immediately, including at the final step, and keep the
        # existing one-turn afterimage before removing the marker.
        recent_death = agent.get("death_step") in (snapshot["step"], snapshot["step"] - 1)
        if agent["alive"] or recent_death:
            cells[tuple(agent["position"])].append(agent)
    for (x, y), agents in cells.items():
        for index, agent in enumerate(sorted(agents, key=lambda item: item["id"])):
            angle = 2 * math.pi * index / len(agents)
            offset = 0.25 if len(agents) > 1 else 0
            point = (x + offset * math.cos(angle), y + offset * math.sin(angle))
            states = agent_states(agent, events.get(agent["id"]), victims)
            prefix = "agent" if agent["alive"] else "death"
            add_icon(ax, states[0], point, size, f"{prefix}-{agent['id']}")
            if len(states) > 1:
                add_icon(ax, states[1], point, size * 0.6, f"damage-{agent['id']}",
                         zorder=5, offset=(size * 0.4, size * 0.3))
            ax.annotate(f"{agent['id']:02d}", point, xytext=(size * 0.35, -size * 0.6),
                        textcoords="offset points", fontsize=13, fontweight="bold", color="#1e293b",
                        bbox={"boxstyle": "round,pad=0.12", "facecolor": "white",
                              "edgecolor": "none", "alpha": 0.92}, zorder=6)

    spacing = max(1, grid_size // 10)
    ax.set_xticks(range(0, grid_size, spacing))
    ax.set_yticks(range(0, grid_size, spacing))
    ax.set_xticks([i - 0.5 for i in range(grid_size + 1)], minor=True)
    ax.set_yticks([i - 0.5 for i in range(grid_size + 1)], minor=True)
    ax.grid(which="minor", color="#eee9df", linewidth=0.5)
    ax.tick_params(which="minor", length=0)
    ax.tick_params(colors="#94a3b8", labelsize=8)
    ax.set(xlim=(-0.5, grid_size - 0.5), ylim=(grid_size - 0.5, -0.5),
           xlabel="X", ylabel="Y", aspect="equal", title=f"Step {snapshot['step']}")
    for spine in ax.spines.values():
        spine.set_color("#e2ddd3")
    fig.subplots_adjust(left=0.07, right=0.98, top=0.95, bottom=0.07)
    return fig
