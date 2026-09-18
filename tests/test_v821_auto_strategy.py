import json
from pathlib import Path
import numpy as np
import torch

from scripts import draft_v821_auto_strategy as v821
from web.backend.services.draft_ml.v82_strategy import (StrategyDataset,StrategyEnsemble,StrategyScorerV2,
    fit_strategy_v2,strategy_loss_v2)


def row(profiles=6):
    features=torch.randn(profiles,12,7);features[:,:,5]=1
    masks=torch.zeros(profiles,12,dtype=torch.bool);masks[:,:8]=True
    for index in range(profiles): features[index,index%8,5]=0
    return {'features':features,'masks':masks,'globals':torch.randn(profiles,5),'utilities':torch.linspace(.2,.8,profiles)}


def settings():
    return {'target_temperature':.7,'prediction_temperature':1.,'pairwise_margin':.5,
      'listwise_weight':1.,'pairwise_weight':.5,'regression_weight':.15}


def test_category_binding_changes_score_for_different_punts():
    torch.manual_seed(4);model=StrategyScorerV2(16,4,1).eval();sample=row(3)
    sample['features'][0,:,5]=1;sample['features'][1]=sample['features'][0];sample['features'][2]=sample['features'][0]
    sample['features'][1,0,5]=0;sample['features'][2,1,5]=0
    with torch.inference_mode():scores=model(sample['features'],sample['masks'],sample['globals'][0].repeat(3,1))
    assert not torch.isclose(scores[1],scores[2])


def test_listwise_loss_backpropagates_and_ranks():
    model=StrategyScorerV2(16,4,1);sample=row();loss,metrics=strategy_loss_v2(model,sample,settings())
    loss.backward();assert torch.isfinite(loss) and 0<=metrics['top1']<=1
    assert any(parameter.grad is not None for parameter in model.parameters())


def write_shard(path,scenario):
    sample=row(5)
    np.savez_compressed(path,features=sample['features'].numpy().astype(np.float32),masks=sample['masks'].numpy(),
      globals=sample['globals'].numpy().astype(np.float32),utilities=sample['utilities'].numpy().astype(np.float32),scenario=np.asarray(scenario))


def test_v2_training_and_ensemble_loading(tmp_path):
    data=tmp_path/'data';(data/'train').mkdir(parents=True);(data/'validation').mkdir()
    write_shard(data/'train/a.npz','train');write_shard(data/'validation/b.npz','validation')
    config={'training':{**settings(),'epochs':1,'width':16,'heads':4,'layers':1,'learning_rate':1e-3,
      'weight_decay':.01,'patience':1,'minimum_improvement':1e-5,'device':'cpu'}}
    paths=[]
    for seed in (1,2,3):
        output=tmp_path/f'seed-{seed}';fit_strategy_v2(config,data,output,'test',seed);paths.append(output/'best.pt')
    ensemble=StrategyEnsemble(paths);sample=row(4)
    matrix=ensemble.score_matrix(sample['features'].numpy(),sample['masks'].numpy(),sample['globals'].numpy())
    assert matrix.shape==(3,4) and np.allclose(matrix.mean(1),0,atol=1e-5)


def test_plan_reuses_labels_and_gate_rejects_collapse():
    plan=v821.plan();assert plan['reused_label_shards']==300 and plan['new_rollout_labels']==0
    assert plan['fresh_validation_drafts']==2376
    gates={'normalized_delta_min':.002,'interval_low_min':-.005,'maximum_profile_share':.7,'minimum_unique_profiles':5}
    base={'primary':{'auto_vs_balanced':{'normalized_categories':{'delta':.01,'interval':[-.001,.02]}}},
          'maximum_profile_share':.5,'unique_profiles':8}
    assert v821.eligible(base,gates)
    base['maximum_profile_share']=.9;assert not v821.eligible(base,gates)
