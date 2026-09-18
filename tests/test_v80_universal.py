import json

import numpy as np
import torch

from web.backend.services.draft_ml.v7_network import NeuralPolicy
from web.backend.services.draft_ml.v7_state import State as V7State
from web.backend.services.draft_ml.v8_network import UniversalPolicy, UniversalPolicyValue, migrate_v7_checkpoint
from web.backend.services.draft_ml.v8_state import CATEGORY_VOCAB, UniversalState, normalize_categories


ROOT = __import__('pathlib').Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'artifacts/draft_ml/standard8/standard8-market-v4-inputs.json'
V76 = ROOT / 'artifacts/draft_ml/standard8-v76-distillation/training/best.pt'


def payload():
    return json.loads(SNAPSHOT.read_text(encoding='utf-8'))


def test_category_alias_and_validation():
    assert normalize_categories(('FG%', '3P%', 'DD')) == ('FG%', '3PT%', 'DD')
    try:
        normalize_categories(('PTS', 'PTS'))
    except ValueError:
        pass
    else:
        raise AssertionError('Duplicate category must fail')


def test_variable_league_and_category_shapes():
    data = payload(); categories = ('FG%', 'FT%', '3PM', '3PT%', 'REB', 'AST', 'A/TO', 'STL', 'BLK', 'DD', 'PTS')
    slots = ('PG', 'SG', 'SF', 'PF', 'C', 'G', 'F', 'UTIL', 'UTIL', 'BE', 'BE')
    state = UniversalState(data['players'], slots, 14, len(slots), categories, category_weights={'FT%': 0.0})
    encoded = state.encode(); model = UniversalPolicyValue(width=32, heads=4, layers=1)
    args = [torch.as_tensor(value).unsqueeze(0) for value in encoded]
    policy, values, events = model(*args)
    assert policy.shape == (1, len(data['players']))
    assert values.shape == (1, len(categories))
    assert events.shape == (1, 3)
    assert encoded[5].max() <= 14
    assert encoded[3][categories.index('FT%'), 0] == 0.0
    state.apply(state.legal()[0])
    history = state.encode()[0][state.rosters[1][0], -2:]
    assert history[0] > 0 and history[1] > 0


def test_v76_migration_is_numerically_equivalent(tmp_path):
    data = payload(); checkpoint = tmp_path / 'v80.pt'
    migrate_v7_checkpoint(V76, checkpoint, 'test')
    old = NeuralPolicy(V76); new = UniversalPolicy(checkpoint)
    state7 = V7State(data['players'], data['roster_slots'], 10, 13)
    state8 = UniversalState(data['players'], data['roster_slots'], 10, 13, data['categories'])
    for index in (0, 7, 15, 22):
        state7.apply(index); state8.apply(index)
    legal = state7.legal()
    old_logits, old_values = old.predict(state7, legal); new_logits, new_values = new.predict(state8, legal)
    assert np.max(np.abs(old_logits[legal] - new_logits[legal])) < 5e-5
    assert np.max(np.abs(old_values - new_values)) < 1e-5
    assert old_logits[legal].argmax() == new_logits[legal].argmax()
