import json
from pathlib import Path
import numpy as np
import torch

from scripts import draft_v82_auto_strategy as v82
from web.backend.services.draft_ml.v82_strategy import StrategyScorer,StrategyPolicy,fit_strategy,strategy_loss

ROOT=Path(__file__).resolve().parents[1]


def test_profile_spaces_and_plan():
    settings,_=v82.configuration();cases=v82.v81.configuration()[1]['formats']
    s8=next(c for c in cases if c['id']=='s8-t10-r13');c11=next(c for c in cases if c['id']=='c11-t10-r13')
    assert len(v82.profiles(s8,settings))==37
    assert len(v82.profiles(c11,settings))==232
    plan=v82.plan();assert plan['label_states']==300 and plan['label_continuations_max']==14400
    assert plan['fresh_2027_projections'] is False


def test_strategy_network_variable_categories_backward():
    model=StrategyScorer(16);features=torch.randn(5,12,7);mask=torch.zeros(5,12,dtype=torch.bool);mask[:,:8]=True
    globals_=torch.randn(5,5);utilities=torch.rand(5)
    settings={'ranking_temperature':.03,'regression_weight':1.,'ranking_weight':.25}
    loss,metrics=strategy_loss(model,{'features':features,'masks':mask,'globals':globals_,'utilities':utilities},settings)
    loss.backward();assert torch.isfinite(loss) and 0<=metrics['top1']<=1


def write_shard(path,scenario):
    profiles=4;features=np.zeros((profiles,12,7),np.float32);features[:,:,5]=1
    masks=np.zeros((profiles,12),np.bool_);masks[:,:8]=True
    np.savez_compressed(path,features=features,masks=masks,globals=np.zeros((profiles,5),np.float32),
                        utilities=np.asarray([.4,.5,.6,.55],np.float32),scenario=np.asarray(scenario))


def test_strategy_training_and_loading(tmp_path):
    data=tmp_path/'data';(data/'train').mkdir(parents=True);(data/'validation').mkdir()
    write_shard(data/'train/a.npz','train');write_shard(data/'validation/b.npz','validation')
    config={'seed':1,'training':{'epochs':1,'width':8,'learning_rate':1e-3,'weight_decay':.01,'patience':1,
      'minimum_improvement':1e-5,'ranking_temperature':.03,'regression_weight':1.,'ranking_weight':.25,'device':'cpu'}}
    fit_strategy(config,data,tmp_path/'training','test');checkpoint=tmp_path/'training/best.pt'
    policy=StrategyPolicy(checkpoint);scores=policy.scores(np.zeros((2,12,7),np.float32),np.ones((2,12),np.bool_),np.zeros((2,5),np.float32))
    assert scores.shape==(2,)


def test_feature_shape_and_profile_signal():
    v82.initialize();settings,_=v82.configuration();case=next(c for c in v82.v81.configuration()[1]['formats'] if c['id']=='s8-t10-r13')
    state,_,_,_=v82.starting_state(case,0,'test');a=v82.state_features(state,case,());b=v82.state_features(state,case,('FG%',))
    assert a[0].shape==(12,7) and a[1].sum()==8 and a[2].shape==(5,)
    assert a[0][0,5]==1 and b[0][0,5]==0
