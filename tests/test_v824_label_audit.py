import json

import numpy as np

from scripts import draft_v824_label_audit as v824


def test_formats_cover_four_families_and_spread_seats():
    formats=v824.audit_formats()
    assert len(formats)==16
    assert {len(case['categories']) for case in formats}=={8,9,10,11}
    assert len([case for case in formats if len(case['categories'])==10])==4
    assert v824.state_indices(14,4)==[0,4,9,13]


def write_profile(directory,index,utilities):
    np.savez_compressed(directory/f'profile-{index:02d}.npz',utilities=np.asarray(utilities,dtype=np.float32))


def test_state_reliability_recognizes_stable_low_regret_labels(tmp_path):
    directory=tmp_path/'raw'/'state';directory.mkdir(parents=True)
    # Eight rollouts x four terminal draws. Profile 1 is consistently superior.
    write_profile(directory,0,np.full((8,4),.40))
    write_profile(directory,1,np.asarray([[.50+i*.001]*4 for i in range(8)]))
    write_profile(directory,2,np.asarray([[.45+i*.001]*4 for i in range(8)]))
    manifest={'state_id':'state','format_id':'s8','category_count':8,'team_count':10,'state_index':0,
              'profiles':[[],['AST'],['PTS']]}
    row=v824.state_reliability(tmp_path,manifest)
    assert row['spearman']>.99 and row['top1_agreement']
    assert row['top3_overlap']==3 and max(row['cross_regrets'])<1e-8
    assert all(row['cross_selected_positive']) and row['best_vs_no_punt_resolved']


def test_aggregate_and_gate_fields_are_decision_relevant():
    row={'spearman':.8,'top1_agreement':True,'top3_overlap':2,'cross_selected_positive':[True,True],
         'cross_regrets':[.002,.003],'profile_sign_agreement':.75,'best_vs_no_punt_resolved':True,
         'full_best_gain':.02,'full_top_second_gap':.01}
    summary=v824.aggregate([row,row])
    assert summary['median_spearman']==.8 and summary['cross_selected_positive']==1
    assert summary['mean_cross_regret']==.0025 and summary['top3_overlap_two']==1


def test_plan_is_measurement_only_and_resumable_at_profile_level():
    plan=v824.plan()
    assert plan['training'] is False and plan['states']==64
    assert plan['profile_shards']==1536 and plan['draft_continuations']==12288
    assert plan['terminal_outcomes']==49152 and not plan['auto_promote']
