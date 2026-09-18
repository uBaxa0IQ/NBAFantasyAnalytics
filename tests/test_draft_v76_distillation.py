import json
import numpy as np
from scripts import draft_v76_distillation as distill
from scripts import draft_v73_diagnostic as base
from test_draft_v73_diagnostic import setup_arena


def prepared(monkeypatch):
    config,settings,payload,arena=setup_arena()
    class Policy:
        def predict(self,state,legal=None):
            logits=np.arange(len(state.players),dtype=np.float32)/10
            logits[[i for i in range(len(state.players)) if i not in state.legal()]]=-1e9
            return logits,np.zeros(11,dtype=np.float32)
    arena.history=[Policy() for _ in range(3)]
    settings.update(late_picks=1,teacher_temperature=.5,search_temperature=.15,old_policy_blend=.25,
                    audit_rollouts=1,audit_min_utility_gain=.02,terminal_draws=2,cheap_candidates=2,cheap_rollouts=1)
    monkeypatch.setattr(base,'CTX',(config,settings,payload,arena))
    monkeypatch.setattr(distill,'NEW',arena.history[2])
    return config,settings,payload,arena


def test_generation_policy_normalized_and_full_legal_loss(tmp_path,monkeypatch):
    prepared(monkeypatch)
    path=tmp_path/'episode.npz'
    row=distill.generate_episode(('train',0,str(path),'test'))
    assert row['searched']==1
    with np.load(path,allow_pickle=False) as data:
        assert np.allclose(data['policy'].sum(1),1)
        assert np.array_equal(data['loss_mask'],data['legal'])
        assert np.all(data['policy'][~data['legal']]==0)
        assert data['value'].shape==(3,11)
        assert len(json.loads(str(data['audits'])))==1
        assert str(data['scenario']).startswith('v76:')


def test_evaluation_preserves_frozen_opponents_and_paired_baselines(monkeypatch):
    _,_,_,arena=prepared(monkeypatch)
    old=list(arena.history)
    row=distill.evaluate_episode(('validation','strong',0))
    assert row['results']['old']==row['results']['new']
    assert row['results']['old_cheap']==row['results']['new_cheap']
    assert arena.history==old
    result=distill.report([row,row])
    assert result['primary']['new_vs_old']['categories']['delta']==0


def test_improvement_audit_failure_preserves_old_target(monkeypatch):
    config,settings,payload,arena=prepared(monkeypatch)
    state=distill.State(payload['players'],payload['roster_slots'],2,3)
    settings['audit_min_utility_gain']=1e6
    policy,action,info=distill.improved_target(state,1,arena,settings,'unit')
    logits,_=arena.history[2].predict(state)
    assert not info['accepted']
    assert action==max(state.legal(),key=lambda i:logits[i])
    assert np.allclose(policy[state.legal()],distill.softmax(logits[state.legal()],settings['teacher_temperature']))


def test_generated_shards_train_and_resume(tmp_path,monkeypatch):
    config,settings,_,_=prepared(monkeypatch)
    for split in ('train','validation'):
        distill.generate_episode((split,0,str(tmp_path/'data'/split/'000000.npz'),'test'))
    from web.backend.services.draft_ml.v7_train import fit
    from web.backend.services.draft_ml.v7_network import PolicyValue,atomic_torch,NeuralPolicy
    model=PolicyValue(**config['model'],team_count=2)
    initial=tmp_path/'initial.pt'
    atomic_torch(initial,dict(model=model.state_dict(),spec=model.spec,provenance='initial'))
    fit(config,tmp_path/'data',tmp_path/'trained','test',warm_start=initial)
    before=(tmp_path/'trained/best.pt').read_bytes()
    fit(config,tmp_path/'data',tmp_path/'trained','test',warm_start=initial)
    assert (tmp_path/'trained/best.pt').read_bytes()==before
    assert NeuralPolicy(tmp_path/'trained/best.pt').model.spec['team_count']==2
