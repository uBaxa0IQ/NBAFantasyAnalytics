"""Universal automatic punt/strategy scorer for V8.2."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler

from .v8_state import CATEGORY_TO_ID, CATEGORY_VOCAB

STRATEGY_FEATURES = 7
STRATEGY_GLOBAL = 5


class StrategyScorer(nn.Module):
    def __init__(self, width=48):
        super().__init__(); self.width = int(width)
        self.category = nn.Embedding(len(CATEGORY_VOCAB), width)
        self.feature = nn.Linear(STRATEGY_FEATURES, width)
        self.global_project = nn.Linear(STRATEGY_GLOBAL, width)
        self.score = nn.Sequential(nn.Linear(width * 3, width), nn.GELU(), nn.Linear(width, 1))
        self.spec = {'architecture': 'universal_strategy_v1', 'width': width,
                     'category_vocab': list(CATEGORY_VOCAB), 'features': STRATEGY_FEATURES,
                     'global_features': STRATEGY_GLOBAL}

    def forward(self, features, mask, global_state):
        ids = torch.arange(len(CATEGORY_VOCAB), device=features.device)
        token = self.feature(features) + self.category(ids)[None]
        active = mask.unsqueeze(-1).to(token.dtype); denominator = active.sum(1).clamp_min(1)
        mean = (token * active).sum(1) / denominator
        maximum = token.masked_fill(~mask.unsqueeze(-1), -1e9).max(1).values
        hidden = torch.cat((mean, maximum, self.global_project(global_state)), dim=-1)
        return self.score(hidden).squeeze(-1)


class StrategyPolicy:
    def __init__(self, checkpoint, device='cpu'):
        payload = torch.load(checkpoint, map_location='cpu', weights_only=True)
        if payload['spec'].get('architecture') != 'universal_strategy_v1' or \
                payload['spec'].get('category_vocab') != list(CATEGORY_VOCAB):
            raise ValueError('Incompatible V8.2 strategy checkpoint')
        self.model = StrategyScorer(payload['spec']['width']).to(device).eval()
        self.model.load_state_dict(payload['model']); self.device = torch.device(device)

    @torch.inference_mode()
    def scores(self, features, masks, globals_):
        return self.model(torch.as_tensor(features, device=self.device),
                          torch.as_tensor(masks, device=self.device),
                          torch.as_tensor(globals_, device=self.device)).cpu().numpy()


class StrategyScorerV2(nn.Module):
    """Category-bound scorer: candidate weights interact before attention/pooling."""
    def __init__(self, width=64, heads=4, layers=2):
        super().__init__(); self.width=int(width); self.heads=int(heads); self.layers=int(layers)
        self.category=nn.Embedding(len(CATEGORY_VOCAB),width)
        self.state=nn.Sequential(nn.Linear(6,width),nn.GELU(),nn.Linear(width,width))
        self.binding=nn.Sequential(nn.Linear(width*2+1,width),nn.GELU(),nn.Linear(width,width))
        layer=nn.TransformerEncoderLayer(width,heads,width*2,dropout=0.05,batch_first=True,norm_first=True)
        self.encoder=nn.TransformerEncoder(layer,layers,enable_nested_tensor=False)
        self.global_project=nn.Sequential(nn.Linear(STRATEGY_GLOBAL,width),nn.GELU(),nn.Linear(width,width))
        self.score=nn.Sequential(nn.Linear(width*5,width),nn.GELU(),nn.Linear(width,1))
        self.spec={'architecture':'universal_strategy_v2','width':width,'heads':heads,'layers':layers,
                   'category_vocab':list(CATEGORY_VOCAB),'features':STRATEGY_FEATURES,'global_features':STRATEGY_GLOBAL}

    def forward(self,features,mask,global_state):
        ids=torch.arange(len(CATEGORY_VOCAB),device=features.device)
        # State statistics exclude candidate keep/punt weight (column 5), while
        # reverse-category direction (column 6) remains part of league state.
        state_features=torch.cat((features[:,:,:5],features[:,:,6:7]),dim=-1)
        base=self.category(ids)[None]+self.state(state_features)
        keep=features[:,:,5:6]
        token=base+self.binding(torch.cat((base,base*(2*keep-1),keep),dim=-1))
        token=self.encoder(token,src_key_padding_mask=~mask)
        active=mask.unsqueeze(-1).to(token.dtype); kept=active*keep; punted=active*(1-keep)
        mean=(token*active).sum(1)/active.sum(1).clamp_min(1)
        kept_mean=(token*kept).sum(1)/kept.sum(1).clamp_min(1)
        punt_mean=(token*punted).sum(1)/punted.sum(1).clamp_min(1)
        maximum=token.masked_fill(~mask.unsqueeze(-1),-1e9).max(1).values
        hidden=torch.cat((mean,maximum,kept_mean,punt_mean,self.global_project(global_state)),dim=-1)
        return self.score(hidden).squeeze(-1)


class StrategyEnsemble:
    def __init__(self,checkpoints,device='cpu'):
        self.models=[]; self.device=torch.device(device)
        for checkpoint in checkpoints:
            payload=torch.load(checkpoint,map_location='cpu',weights_only=True);spec=payload['spec']
            if spec.get('architecture')!='universal_strategy_v2': raise ValueError('V8.2.1 checkpoint required')
            model=StrategyScorerV2(spec['width'],spec['heads'],spec['layers']).to(device).eval();model.load_state_dict(payload['model'])
            self.models.append(model)

    @torch.inference_mode()
    def score_matrix(self,features,masks,globals_):
        args=(torch.as_tensor(features,device=self.device),torch.as_tensor(masks,device=self.device),torch.as_tensor(globals_,device=self.device))
        rows=[]
        for model in self.models:
            score=model(*args); score=(score-score.mean())/score.std().clamp_min(1e-6);rows.append(score)
        return torch.stack(rows).cpu().numpy()


class StrategyDataset(Dataset):
    def __init__(self, directory):
        self.paths = sorted(Path(directory).glob('*.npz'))
        if not self.paths: raise ValueError(f'No strategy shards: {directory}')
        self.scenarios = set()
        for path in self.paths:
            with np.load(path, allow_pickle=False) as data: self.scenarios.add(str(data['scenario']))

    def __len__(self): return len(self.paths)

    def __getitem__(self, index):
        with np.load(self.paths[index], allow_pickle=False) as data:
            return {key: torch.from_numpy(data[key].copy()) for key in ('features', 'masks', 'globals', 'utilities')}


def strategy_loss(model, row, settings):
    scores = model(row['features'], row['masks'], row['globals'])
    utilities = row['utilities']; centered = utilities - utilities.mean()
    regression = F.smooth_l1_loss(scores, utilities)
    temperature = settings['ranking_temperature']
    target = F.softmax(centered / temperature, dim=0)
    ranking = -(target * F.log_softmax(scores / temperature, dim=0)).sum()
    loss = settings['regression_weight'] * regression + settings['ranking_weight'] * ranking
    return loss, {'loss': float(loss.detach()), 'regression': float(regression.detach()),
                  'ranking': float(ranking.detach()), 'top1': float(scores.argmax() == utilities.argmax())}


def strategy_loss_v2(model,row,settings):
    scores=model(row['features'],row['masks'],row['globals']);utilities=row['utilities']
    target=(utilities-utilities.mean())/utilities.std().clamp_min(1e-6)
    predicted=(scores-scores.mean())/scores.std().clamp_min(1e-6)
    target_probability=F.softmax(target/settings['target_temperature'],dim=0)
    listwise=-(target_probability*F.log_softmax(predicted/settings['prediction_temperature'],dim=0)).sum()
    best=utilities.argmax(); others=torch.arange(len(scores),device=scores.device)!=best
    pairwise=F.softplus(settings['pairwise_margin']-(predicted[best]-predicted[others])).mean()
    regression=F.smooth_l1_loss(predicted,target)
    loss=settings['listwise_weight']*listwise+settings['pairwise_weight']*pairwise+settings['regression_weight']*regression
    return loss,{'loss':float(loss.detach()),'listwise':float(listwise.detach()),'pairwise':float(pairwise.detach()),
                 'regression':float(regression.detach()),'top1':float(scores.argmax()==best)}


def atomic_torch(path, payload):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); temp=path.with_suffix(path.suffix+'.tmp')
    torch.save(payload,temp)
    for attempt in range(21):
        try: os.replace(temp,path); return
        except PermissionError:
            if attempt==20: raise
            time.sleep(.2)


def atomic_json(path, payload):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(payload,indent=2),encoding='utf-8')
    for attempt in range(21):
        try: os.replace(temp,path); return
        except PermissionError:
            if attempt==20: raise
            time.sleep(.2)


def fit_strategy(config, data, output, provenance):
    settings=config['training']; output=Path(output); output.mkdir(parents=True,exist_ok=True)
    train=StrategyDataset(Path(data)/'train'); validation=StrategyDataset(Path(data)/'validation')
    if train.scenarios & validation.scenarios: raise ValueError('Strategy train/validation leakage')
    device=('cuda' if torch.cuda.is_available() else 'cpu') if settings['device']=='auto' else settings['device']
    torch.manual_seed(config['seed']); np.random.seed(config['seed']%(2**32)); torch.cuda.manual_seed_all(config['seed'])
    model=StrategyScorer(settings['width']).to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=settings['learning_rate'],weight_decay=settings['weight_decay'])
    latest=output/'last.pt'; start=0; best=float('inf'); stale=0; history=[]
    if latest.exists():
        saved=torch.load(latest,map_location=device,weights_only=True)
        if saved['provenance']!=provenance: raise ValueError('Strategy resume mismatch')
        model.load_state_dict(saved['model']); optimizer.load_state_dict(saved['optimizer'])
        start,best,stale,history=saved['epoch'],saved['best'],saved['stale'],saved['history']
    if (output/'complete.json').exists(): return
    for epoch in range(start,settings['epochs']):
        if stale>=settings['patience']: break
        generator=torch.Generator().manual_seed(config['seed']+epoch)
        loader=DataLoader(train,batch_size=None,shuffle=True,generator=generator)
        model.train()
        for row in loader:
            row={k:v.to(device) for k,v in row.items()}; optimizer.zero_grad(set_to_none=True)
            loss,_=strategy_loss(model,row,settings); loss.backward(); nn.utils.clip_grad_norm_(model.parameters(),1); optimizer.step()
        model.eval(); sums={}; count=0
        with torch.inference_mode():
            for row in DataLoader(validation,batch_size=None,shuffle=False):
                row={k:v.to(device) for k,v in row.items()}; _,metrics=strategy_loss(model,row,settings); count+=1
                for key,value in metrics.items(): sums[key]=sums.get(key,0)+value
        metrics={key:value/count for key,value in sums.items()}; history.append({'epoch':epoch+1,**metrics})
        improved=metrics['loss']<best-settings['minimum_improvement']; best,stale=(metrics['loss'],0) if improved else (best,stale+1)
        checkpoint={'model':model.state_dict(),'spec':model.spec,'provenance':provenance}
        if improved: atomic_torch(output/'best.pt',checkpoint)
        atomic_torch(latest,{**checkpoint,'optimizer':optimizer.state_dict(),'epoch':epoch+1,'best':best,'stale':stale,'history':history})
        print(json.dumps({'epoch':epoch+1,'device':device,**metrics}),flush=True)
    atomic_json(output/'complete.json',{'provenance':provenance,'epochs':len(history),'best_loss':best,'history':history})


def fit_strategy_v2(config,data,output,provenance,seed):
    settings=config['training'];output=Path(output);output.mkdir(parents=True,exist_ok=True)
    train=StrategyDataset(Path(data)/'train');validation=StrategyDataset(Path(data)/'validation')
    if train.scenarios&validation.scenarios:raise ValueError('V8.2.1 train/validation leakage')
    device=('cuda' if torch.cuda.is_available() else 'cpu') if settings['device']=='auto' else settings['device']
    torch.manual_seed(seed);np.random.seed(seed%(2**32));torch.cuda.manual_seed_all(seed)
    model=StrategyScorerV2(settings['width'],settings['heads'],settings['layers']).to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=settings['learning_rate'],weight_decay=settings['weight_decay'])
    latest=output/'last.pt';start=0;best=float('inf');stale=0;history=[]
    if latest.exists():
        saved=torch.load(latest,map_location=device,weights_only=True)
        if saved['provenance']!=provenance or saved['seed']!=seed:raise ValueError('V8.2.1 resume mismatch')
        model.load_state_dict(saved['model']);optimizer.load_state_dict(saved['optimizer'])
        start,best,stale,history=saved['epoch'],saved['best'],saved['stale'],saved['history']
    if (output/'complete.json').exists():return
    for epoch in range(start,settings['epochs']):
        if stale>=settings['patience']:break
        generator=torch.Generator().manual_seed(seed+epoch);loader=DataLoader(train,batch_size=None,shuffle=True,generator=generator)
        model.train()
        for row in loader:
            row={k:v.to(device) for k,v in row.items()};optimizer.zero_grad(set_to_none=True)
            loss,_=strategy_loss_v2(model,row,settings);loss.backward();nn.utils.clip_grad_norm_(model.parameters(),1);optimizer.step()
        model.eval();sums={};count=0
        with torch.inference_mode():
            for row in DataLoader(validation,batch_size=None,shuffle=False):
                row={k:v.to(device) for k,v in row.items()};_,metrics=strategy_loss_v2(model,row,settings);count+=1
                for key,value in metrics.items():sums[key]=sums.get(key,0)+value
        metrics={key:value/count for key,value in sums.items()};history.append({'epoch':epoch+1,**metrics})
        improved=metrics['loss']<best-settings['minimum_improvement'];best,stale=(metrics['loss'],0) if improved else(best,stale+1)
        checkpoint={'model':model.state_dict(),'spec':model.spec,'provenance':provenance,'seed':seed}
        if improved:atomic_torch(output/'best.pt',checkpoint)
        atomic_torch(latest,{**checkpoint,'optimizer':optimizer.state_dict(),'epoch':epoch+1,'best':best,'stale':stale,'history':history})
        print(json.dumps({'seed':seed,'epoch':epoch+1,'device':device,**metrics}),flush=True)
    atomic_json(output/'complete.json',{'provenance':provenance,'seed':seed,'epochs':len(history),'best_loss':best,'history':history})


class StrategyScorerV3(nn.Module):
    """Format-routed category scorer used by V8.2.2.

    Routing only sees league/state context, never the candidate punt mask.  Every
    expert therefore evaluates all candidate profiles for a state on the same
    scale, while the category binding still models the exact punt combination.
    """
    def __init__(self,width=72,heads=4,layers=2,experts=4):
        super().__init__();self.width=int(width);self.heads=int(heads);self.layers=int(layers);self.experts=int(experts)
        self.category=nn.Embedding(len(CATEGORY_VOCAB),width)
        self.state=nn.Sequential(nn.Linear(6,width),nn.GELU(),nn.Linear(width,width))
        self.binding=nn.Sequential(nn.Linear(width*2+1,width),nn.GELU(),nn.Linear(width,width))
        layer=nn.TransformerEncoderLayer(width,heads,width*3,dropout=.06,batch_first=True,norm_first=True)
        self.encoder=nn.TransformerEncoder(layer,layers,enable_nested_tensor=False)
        self.global_project=nn.Sequential(nn.Linear(STRATEGY_GLOBAL,width),nn.GELU(),nn.Linear(width,width))
        self.format_project=nn.Sequential(nn.Linear(4,width),nn.GELU(),nn.Linear(width,width))
        self.router=nn.Sequential(nn.Linear(width*2,width),nn.GELU(),nn.Linear(width,experts))
        hidden_width=width*5
        self.expert_heads=nn.ModuleList([
            nn.Sequential(nn.Linear(hidden_width,width),nn.GELU(),nn.Linear(width,1)) for _ in range(experts)
        ])
        self.category_value=nn.Sequential(nn.Linear(width,width//2),nn.GELU(),nn.Linear(width//2,1))
        self.spec={'architecture':'universal_strategy_v3','width':width,'heads':heads,'layers':layers,'experts':experts,
                   'category_vocab':list(CATEGORY_VOCAB),'features':STRATEGY_FEATURES,'global_features':STRATEGY_GLOBAL,
                   'router_candidate_independent':True}

    def forward(self,features,mask,global_state):
        ids=torch.arange(len(CATEGORY_VOCAB),device=features.device)
        state_features=torch.cat((features[:,:,:5],features[:,:,6:7]),dim=-1)
        base=self.category(ids)[None]+self.state(state_features)
        keep=features[:,:,5:6]
        token=base+self.binding(torch.cat((base,base*(2*keep-1),keep),dim=-1))
        token=self.encoder(token,src_key_padding_mask=~mask)
        active=mask.unsqueeze(-1).to(token.dtype);kept=active*keep;punted=active*(1-keep)
        denominator=active.sum(1).clamp_min(1)
        mean=(token*active).sum(1)/denominator
        kept_mean=(token*kept).sum(1)/kept.sum(1).clamp_min(1)
        punt_mean=(token*punted).sum(1)/punted.sum(1).clamp_min(1)
        maximum=token.masked_fill(~mask.unsqueeze(-1),-1e9).max(1).values
        global_hidden=self.global_project(global_state)
        hidden=torch.cat((mean,maximum,kept_mean,punt_mean,global_hidden),dim=-1)

        # State features and the first four globals are identical for every
        # profile in a draft state.  Excluding punt-count prevents routing by
        # the answer being scored.
        format_state=(base*active).sum(1)/denominator
        routing=F.softmax(self.router(torch.cat((format_state,self.format_project(global_state[:,:4])),dim=-1)),dim=-1)
        expert_scores=torch.cat([head(hidden) for head in self.expert_heads],dim=-1)
        mixture=(routing*expert_scores).sum(-1)
        contribution=(self.category_value(token).squeeze(-1)*mask).sum(1)/mask.sum(1).clamp_min(1).sqrt()
        return mixture+contribution


class StrategyEnsembleV3:
    def __init__(self,checkpoints,device='cpu'):
        self.models=[];self.device=torch.device(device)
        for checkpoint in checkpoints:
            payload=torch.load(checkpoint,map_location='cpu',weights_only=True);spec=payload['spec']
            if spec.get('architecture')!='universal_strategy_v3':raise ValueError('V8.2.2 checkpoint required')
            if spec.get('category_vocab')!=list(CATEGORY_VOCAB):raise ValueError('V8.2.2 category vocabulary mismatch')
            model=StrategyScorerV3(spec['width'],spec['heads'],spec['layers'],spec['experts']).to(device).eval()
            model.load_state_dict(payload['model']);self.models.append(model)

    @torch.inference_mode()
    def score_matrix(self,features,masks,globals_):
        args=(torch.as_tensor(features,device=self.device),torch.as_tensor(masks,device=self.device),torch.as_tensor(globals_,device=self.device))
        rows=[]
        for model in self.models:
            score=model(*args);score=(score-score.mean())/score.std().clamp_min(1e-6);rows.append(score)
        return torch.stack(rows).cpu().numpy()


class StrategyBalancedDataset(StrategyDataset):
    """Scenario sampler that reduces dominance by common oracle profiles."""
    def __init__(self,directory,exponent=.5,max_multiplier=4.):
        super().__init__(directory);keys=[]
        for path in self.paths:
            with np.load(path,allow_pickle=False) as data:
                profiles=json.loads(str(data['profiles']));best=tuple(profiles[int(data['utilities'].argmax())])
                category_count=int(data['masks'][0].sum());keys.append(f'{category_count}:{best}')
        counts={key:keys.count(key) for key in set(keys)}
        raw=np.asarray([counts[key]**(-float(exponent)) for key in keys],dtype=np.float64);raw/=raw.mean()
        self.sample_weights=np.minimum(raw,float(max_multiplier));self.oracle_counts=counts


def strategy_loss_v3(model,row,settings):
    scores=model(row['features'],row['masks'],row['globals']);utilities=row['utilities']
    target=(utilities-utilities.mean())/utilities.std().clamp_min(1e-6)
    predicted=(scores-scores.mean())/scores.std().clamp_min(1e-6)
    target_probability=F.softmax(target/settings['target_temperature'],dim=0)
    listwise=-(target_probability*F.log_softmax(predicted/settings['prediction_temperature'],dim=0)).sum()
    left,right=torch.triu_indices(len(scores),len(scores),offset=1,device=scores.device)
    differences=target[left]-target[right];weights=differences.abs().clamp_min(.05).clamp_max(3.)
    pairwise=(F.softplus(settings['pairwise_margin']-differences.sign()*(predicted[left]-predicted[right]))*weights).sum()/weights.sum()
    regression=F.smooth_l1_loss(predicted,target)
    loss=settings['listwise_weight']*listwise+settings['pairwise_weight']*pairwise+settings['regression_weight']*regression
    order=scores.argsort(descending=True);best=utilities.argmax();regret=utilities[best]-utilities[order[0]]
    return loss,{'loss':float(loss.detach()),'listwise':float(listwise.detach()),'pairwise':float(pairwise.detach()),
                 'regression':float(regression.detach()),'regret':float(regret.detach()),
                 'top1':float(order[0]==best),'top3':float((order[:min(3,len(order))]==best).any())}


def fit_strategy_v3(config,data,output,provenance,seed):
    settings=config['training'];output=Path(output);output.mkdir(parents=True,exist_ok=True)
    train=StrategyBalancedDataset(Path(data)/'train',settings['balance_exponent'],settings['maximum_sample_multiplier'])
    validation=StrategyDataset(Path(data)/'validation')
    if train.scenarios&validation.scenarios:raise ValueError('V8.2.2 train/validation leakage')
    device=('cuda' if torch.cuda.is_available() else 'cpu') if settings['device']=='auto' else settings['device']
    torch.manual_seed(seed);np.random.seed(seed%(2**32));torch.cuda.manual_seed_all(seed)
    model=StrategyScorerV3(settings['width'],settings['heads'],settings['layers'],settings['experts']).to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=settings['learning_rate'],weight_decay=settings['weight_decay'])
    latest=output/'last.pt';start=0;best=float('inf');stale=0;history=[]
    if latest.exists():
        saved=torch.load(latest,map_location=device,weights_only=True)
        if saved['provenance']!=provenance or saved['seed']!=seed:raise ValueError('V8.2.2 resume mismatch')
        model.load_state_dict(saved['model']);optimizer.load_state_dict(saved['optimizer'])
        start,best,stale,history=saved['epoch'],saved['best'],saved['stale'],saved['history']
    if (output/'complete.json').exists():return
    for epoch in range(start,settings['epochs']):
        if stale>=settings['patience']:break
        generator=torch.Generator().manual_seed(seed+epoch)
        sampler=WeightedRandomSampler(torch.as_tensor(train.sample_weights,dtype=torch.double),len(train),replacement=True,generator=generator)
        loader=DataLoader(train,batch_size=None,sampler=sampler)
        model.train()
        for row in loader:
            row={k:v.to(device) for k,v in row.items()};optimizer.zero_grad(set_to_none=True)
            loss,_=strategy_loss_v3(model,row,settings);loss.backward();nn.utils.clip_grad_norm_(model.parameters(),1);optimizer.step()
        model.eval();sums={};count=0
        with torch.inference_mode():
            for row in DataLoader(validation,batch_size=None,shuffle=False):
                row={k:v.to(device) for k,v in row.items()};_,metrics=strategy_loss_v3(model,row,settings);count+=1
                for key,value in metrics.items():sums[key]=sums.get(key,0)+value
        metrics={key:value/count for key,value in sums.items()}
        selection_metric=metrics['loss']+settings['validation_regret_weight']*metrics['regret']
        history.append({'epoch':epoch+1,'selection_metric':selection_metric,**metrics})
        improved=selection_metric<best-settings['minimum_improvement'];best,stale=(selection_metric,0) if improved else(best,stale+1)
        checkpoint={'model':model.state_dict(),'spec':model.spec,'provenance':provenance,'seed':seed,
                    'balance':{'oracle_counts':train.oracle_counts,'exponent':settings['balance_exponent'],
                               'maximum_sample_multiplier':settings['maximum_sample_multiplier']}}
        if improved:atomic_torch(output/'best.pt',checkpoint)
        atomic_torch(latest,{**checkpoint,'optimizer':optimizer.state_dict(),'epoch':epoch+1,'best':best,'stale':stale,'history':history})
        print(json.dumps({'seed':seed,'epoch':epoch+1,'device':device,'selection_metric':selection_metric,**metrics}),flush=True)
    atomic_json(output/'complete.json',{'provenance':provenance,'seed':seed,'epochs':len(history),
                'best_selection_metric':best,'oracle_counts':train.oracle_counts,'history':history})
