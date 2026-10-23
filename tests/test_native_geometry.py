import ctypes
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch

import native_geometry as native
from geometry_scenarios import scenario
from main import Environment, LLMAgent
from response_fields import _absolute_move

DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1))


class GeometryTests(unittest.TestCase):
    def test_relative_and_visibility_match_pre_migration_python(self):
        # Test-only oracle from e81e4d2; no Python production fallback.
        rng = random.Random(20261023)
        for size in (1, 2, 3, 10, 11, 30, 1000, (1 << 63) - 1):
            for _ in range(100):
                origin = tuple(rng.randrange(-size, size) for _ in range(2))
                targets = [tuple(rng.randrange(-size, size) for _ in range(2)) for _ in range(20)]
                radius = rng.randrange(0, size + 1)
                expected = []
                for index, target in enumerate(targets):
                    offset = tuple((b - a + size // 2) % size - size // 2 for a, b in zip(origin, target))
                    self.assertEqual(native.relative(origin, target, size), offset)
                    visible = all(abs(delta) <= radius for delta in offset)
                    self.assertEqual(native.in_range(origin, target, size, radius), visible)
                    if visible:
                        expected.append((index, *offset))
                self.assertEqual(native.visible_offsets(origin, targets, size, radius), expected)
        self.assertEqual(native.visible_offsets((0, 0), [], 1, 0), [])
        self.assertFalse(native.in_range((0, 0), (0, 0), 1, -1))

    def test_all_small_grid_destinations_preserve_ambiguity_order_and_signs(self):
        for size in range(1, 9):
            for x in range(size):
                for y in range(size):
                    for toward in (None, (0, 0), (1, -1), (-10**100, 10**100)):
                        expected = []
                        for delta in DIRECTIONS:
                            if toward is not None and not any(delta[axis] * toward[axis] > 0 for axis in (0, 1)):
                                continue
                            target = [(position + step) % size for position, step in zip((x, y), delta)]
                            if not any(choice['position'] == target for choice in expected):
                                expected.append({'position': target, 'delta': list(delta)})
                        self.assertEqual(native.cardinal_destinations((x, y), size, toward_delta=toward), expected)
                    for tx in range(size):
                        for ty in range(size):
                            matches = [delta for delta in DIRECTIONS
                                       if ((x + delta[0]) % size, (y + delta[1]) % size) == (tx, ty)]
                            self.assertEqual(_absolute_move((tx, ty), (x, y), size),
                                             matches[0] if len(matches) == 1 else None)

    def test_local_view_keeps_order_and_excludes_self_dead_and_hidden_agents(self):
        environment = Environment(10)
        environment.energy_sources = {(8, 0): 50, (0, 0): 50, (4, 0): 50}
        observer = LLMAgent(3, (9, 0))
        observer.messages = ['受信済み']
        others = [LLMAgent(2, (0, 0), mbti_type='INTP', use_mbti=True),
                  LLMAgent(7, (5, 0)), observer, LLMAgent(1, (8, 0))]
        others[-1].alive = False
        self.assertEqual(observer.get_local_view(environment, others, 2),
                         (['M=(9,0)', 'E=(1,0)', 'E=(-1,0)', '2=(1,0) (MBTI: INTP)'], ['受信済み']))

    def test_invalid_input_and_stale_binary_fail_without_fallback(self):
        with self.assertRaises(OverflowError):
            native.relative((1 << 63, 0), (0, 0), 10)
        with self.assertRaises(ValueError):
            native.relative((0, 0), (1, 1), 0)
        with self.assertRaises(ValueError):
            native.visible_offsets((0, 0), [(1,)], 10, 2)
        with patch.object(native, 'LIBRARY_PATH', Path('/nonexistent/sugarscape-core')):
            with self.assertRaisesRegex(RuntimeError, 'missing or stale'):
                native._load()
        self.assertEqual(native._LIB.ss_relative(0, 0, 0, 0, 1, None, 2), 1)

    def test_arbitrary_large_radius_keeps_whole_grid_visible(self):
        targets = [(x, y) for x in range(10) for y in range(10)]
        self.assertEqual(native.visible_offsets((0, 0), targets, 10, 10**100),
                         native.visible_offsets((0, 0), targets, 10, 5))
        self.assertTrue(native.in_range((0, 0), (5, 5), 10, 10**100))
        self.assertFalse(native.in_range((0, 0), (0, 0), 10, -10**100))


class FullSimulationEquivalenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_world_events_prompts_and_both_random_generators_match_baseline(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/geometry-before-rust.json').read_text())
        for expected in fixture['cases']:
            with self.subTest(size=expected['size'], seed=expected['seed']):
                self.assertEqual(await scenario(expected['size'], expected['seed']), expected)
