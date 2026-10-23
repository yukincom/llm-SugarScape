"""Deterministic integration scenarios, with pre-migration fixture digests."""
import hashlib
import json

from main import Simulation, parse_response


async def scenario(size, seed):
    sim = Simulation(num_agents=4, grid_size=size, seed=seed, use_mbti=True,
                     initial_energy=12, child_initial_energy=8, reproduce_cost=6,
                     spawn_energy_count=min(20, size * size), energy_spawn_rate=0.5,
                     population_cap=20, view_range=2, message_range=3, mock_mode=True)
    sim.run_id = f'geometry-oracle-{size}-{seed}'
    sim.agents[0].position = (size - 1, 0)
    sim.agents[1].position = (0, 0)
    sim.agents[2].position = (0, size - 1)
    sim.agents[3].position = (size // 2, size // 2)

    async def decide(session, agent, system_prompt, user_prompt):
        target = (agent.id + 1) % 4
        action = ('x+1', 'y-1', 'reproduce', f'Share: {target}-3',
                  f'Attack: {target}', 'stay', 'x-1')[(sim.step_count + agent.id) % 7]
        raw = (f'Summary: 状況 {sim.step_count}\nThoughts: geometry baseline\n'
               f'Next Action: {action}\nShare: none\nAttack: none\n'
               f'Message: agent {agent.id} の発言\nMemory: remember {sim.step_count}')
        return {'agent_id': agent.id, 'decision_source': 'mock', 'decision_status': 'ok',
                'error_kind': '', 'reason': '', 'raw_response': raw,
                'system_prompt': system_prompt, 'user_prompt': user_prompt,
                **parse_response(raw, position=agent.position, grid_size=size)}
    sim._request_decision = decide

    def digest(snapshot):
        complete = {'snapshot': snapshot, 'world_rng': sim.rng.getstate(),
                    'numpy_rng': sim.np_rng.bit_generator.state}
        return hashlib.sha256(json.dumps(complete, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    hashes = [digest(sim.snapshot())]
    for _ in range(20):
        hashes.append(digest(await sim.step()))
    return {'size': size, 'seed': seed, 'sha256': hashes, 'summary': sim.get_summary()}
