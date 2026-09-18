"""Paired V7 evaluation against the same legal V6.3 teacher, with equal search budgets."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import random

import numpy as np

from ..draft_benchmark import _ci95
from .v7_state import State
from .v7_data import initialize_worker, atomic_json, scenario_seed, utility


def evaluate_scenario(job):
    from . import v7_data
    split, episode = job
    config, snapshot, arena, neural = v7_data._WORKER
    seed = scenario_seed(config, 'evaluation-' + split, 0, episode)
    hero = episode % config['team_count'] + 1
    assignments = arena.opponents(seed)
    search_rounds = set(random.Random(seed).sample(range(config['rounds']), min(config['rounds'], config['search']['states_per_episode'])))
    results = {}
    for mode in ('teacher', 'student', 'teacher_search', 'student_search', 'teacher_value_search', 'student_value_search'):
        state = State(snapshot['players'], snapshot['roster_slots'], config['team_count'], config['rounds'])
        while not state.complete:
            if state.slot != hero:
                action = arena.opponent_action(state, assignments, seed)
            else:
                proposal = neural if mode.startswith('student') else None
                if mode.endswith('search') and len(state.rosters[hero]) in search_rounds:
                    # Each pair uses identical continuation/evaluation budgets.
                    bootstrap = '_value_' in mode
                    ids, pi, _, _ = arena.search(state, hero, f'{seed}:pick:{state.pick}', proposal,
                                                continuation=neural if bootstrap else None,
                                                value_horizon=1 if bootstrap else 0)
                    action = ids[int(np.argmax(pi))]
                else:
                    action = arena.order(state, proposal)[0][0]
            state.apply(action)
        results[mode] = state.targets(hero, seed, config['gp_stddev'], config['stat_stddev']).tolist()
    return {'scenario': seed, 'episode': episode, 'results': results}


def report(rows):
    comparisons = {}
    for left, right in (('student', 'teacher'), ('student_search', 'teacher_search'), ('student_search', 'student'),
                        ('student_value_search', 'teacher_value_search'), ('student_value_search', 'student'),
                        ('student_value_search', 'student_search')):
        values = {'categories': [], 'rank_improvement': [], 'top4': []}
        for row in rows:
            a, b = row['results'][left], row['results'][right]
            values['categories'].append(sum(a[:8]) - sum(b[:8]))
            values['rank_improvement'].append((b[8] - a[8]) * 9)
            values['top4'].append(a[9] - b[9])
        comparisons[f'{left}_vs_{right}'] = {key: {'delta': float(np.mean(v)), 'ci95': _ci95(v), 'n': len(v)} for key, v in values.items()}
    return {'comparisons': comparisons, 'paired_outcomes': rows,
            'limitations': ['Same historical player snapshot; new scenario seeds do not constitute a new season.',
                            'Category wins and rank describe projected final rosters, not weekly H2H or playoff odds.',
                            'Opponent policies are market-free anchors and V6.3; this arena does not reproduce all historical ESPN market tests.']}


def evaluate(config, snapshot, teacher, checkpoint, output, split, provenance):
    output = Path(output)
    jobs, rows = [], []
    for episode in range(config['evaluation_runs'][split]):
        path = output / f'{episode:06d}.json'
        if path.exists():
            row = json.loads(path.read_text(encoding='utf-8'))
            if row['provenance'] != provenance:
                raise ValueError('Evaluation provenance mismatch')
            rows.append(row)
        else:
            jobs.append((split, episode))
    # Held-out arena random weights differ from training; validation and holdout differ too.
    offset = 100003 if split == 'validation' else 200003
    with ProcessPoolExecutor(max_workers=config['workers'], initializer=initialize_worker, initargs=(config, str(snapshot), str(teacher), str(checkpoint), False, offset)) as pool:
        futures = {pool.submit(evaluate_scenario, job): job for job in jobs}
        for future in as_completed(futures):
            row = future.result()
            row['provenance'] = provenance
            atomic_json(output / f"{row['episode']:06d}.json", row)
            rows.append(row)
            print(f'evaluation {split} {len(rows)}/{config["evaluation_runs"][split]}', flush=True)
    rows.sort(key=lambda row: row['episode'])
    atomic_json(output / 'summary.json', {**report(rows), 'provenance': provenance})
