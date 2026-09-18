import json

import numpy as np
import torch

from scripts import draft_v822_format_routed as v822
from web.backend.services.draft_ml.v82_strategy import (
    StrategyBalancedDataset,StrategyEnsembleV3,StrategyScorerV3,fit_strategy_v3,strategy_loss_v3,
)


def row(profiles=6):
    features=torch.randn(1,12,7).repeat(profiles,1,1);features[:,:,5]=1
    masks=torch.zeros(profiles,12,dtype=torch.bool);masks[:,:8]=True
    for index in range(1,profiles):features[index,index%8,5]=0
    globals_=torch.randn(profiles,5);globals_[:,:4]=globals_[0,:4]
    globals_[:,4]=torch.linspace(0,.25,profiles)
    return {'features':features,'masks':masks,'globals':globals_,'utilities':torch.linspace(.2,.8,profiles)}


def settings():
    return {'target_temperature':.65,'prediction_temperature':1.,'pairwise_margin':.45,
      'listwise_weight':1.,'pairwise_weight':.65,'regression_weight':.15}


def write_shard(path,scenario,best):
    sample=row(5);utilities=np.asarray([.1,.2,.3,.4,.5],np.float32)
    profiles=[[],['PTS'],['AST'],['REB'],['STL']];utilities[best]=1
    np.savez_compressed(path,features=sample['features'].numpy().astype(np.float32),masks=sample['masks'].numpy(),
      globals=sample['globals'].numpy().astype(np.float32),utilities=utilities,profiles=np.asarray(json.dumps(profiles)),
      scenario=np.asarray(scenario),format_id=np.asarray('s8-test'))


def test_format_routed_model_binds_candidate_and_backpropagates():
    torch.manual_seed(8);model=StrategyScorerV3(16,4,1,3);sample=row()
    router_logits=[];hook=model.router.register_forward_hook(lambda module,args,output:router_logits.append(output.detach()))
    loss,metrics=strategy_loss_v3(model,sample,settings());loss.backward()
    hook.remove()
    assert torch.isfinite(loss) and 0<=metrics['top1']<=1 and 0<=metrics['top3']<=1
    assert torch.allclose(router_logits[0],router_logits[0][0].expand_as(router_logits[0]))
    assert model.spec['router_candidate_independent'] and any(p.grad is not None for p in model.parameters())


def test_balanced_dataset_upweights_rare_oracle_profile(tmp_path):
    data=tmp_path/'data';data.mkdir()
    for index in range(4):write_shard(data/f'common-{index}.npz',f'common-{index}',1)
    write_shard(data/'rare.npz','rare',3)
    dataset=StrategyBalancedDataset(data,.5,4.)
    assert dataset.sample_weights[-1]>dataset.sample_weights[0]
    assert sum(dataset.oracle_counts.values())==5


def test_v3_training_resume_and_ensemble(tmp_path):
    data=tmp_path/'data';(data/'train').mkdir(parents=True);(data/'validation').mkdir()
    write_shard(data/'train/a.npz','train-a',1);write_shard(data/'train/b.npz','train-b',3)
    write_shard(data/'validation/c.npz','validation-c',2)
    config={'training':{**settings(),'epochs':1,'width':16,'heads':4,'layers':1,'experts':2,
      'learning_rate':1e-3,'weight_decay':.01,'patience':1,'minimum_improvement':1e-5,
      'validation_regret_weight':2.,'balance_exponent':.5,'maximum_sample_multiplier':4.,'device':'cpu'}}
    checkpoints=[]
    for seed in (1,2,3):
        output=tmp_path/f'seed-{seed}';fit_strategy_v3(config,data,output,'test',seed);checkpoints.append(output/'best.pt')
    ensemble=StrategyEnsembleV3(checkpoints);sample=row(4)
    matrix=ensemble.score_matrix(sample['features'].numpy(),sample['masks'].numpy(),sample['globals'].numpy())
    assert matrix.shape==(3,4) and np.allclose(matrix.mean(1),0,atol=1e-5)


def test_gate_requires_standard8_value_and_noncollapsed_profiles():
    gates={'normalized_delta_min':.003,'interval_low_min':-.002,'standard8_delta_min':0.,
           'family_delta_min':-.003,'maximum_profile_share':.7,'minimum_unique_profiles':5}
    summary={'primary':{'auto_vs_balanced':{'normalized_categories':{'delta':.01,'interval':[.001,.02]}}},
             'by_category_count':{
                 '8':{'normalized_categories':{'delta':.002}},
                 '9':{'normalized_categories':{'delta':.01}},
                 '11':{'normalized_categories':{'delta':.004}}},
             'maximum_profile_share':.5,'unique_profiles':7}
    assert v822.eligible(summary,gates)
    summary['by_category_count']['8']['normalized_categories']['delta']=-.001
    assert not v822.eligible(summary,gates)
    summary['by_category_count']['8']['normalized_categories']['delta']=.002;summary['unique_profiles']=4
    assert not v822.eligible(summary,gates)


def test_plan_reuses_labels_and_uses_fresh_evaluation_namespaces():
    plan=v822.plan()
    assert plan['reused_label_shards']==300 and plan['new_rollout_labels']==0
    assert plan['fresh_validation_split']=='v822_validation_eval'
    assert plan['sealed_holdout_split']=='v822_holdout' and not plan['auto_promote']
