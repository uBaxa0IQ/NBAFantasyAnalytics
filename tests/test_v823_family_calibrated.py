from scripts import draft_v823_family_calibrated as v823


def test_development_evidence_admits_only_confirmed_family():
    settings,_=v823.configuration();families,evidence=v823.development_families(settings)
    assert families==['9']
    assert evidence['9']['passed'] and not evidence['8']['passed']
    assert not evidence['10']['passed'] and not evidence['11']['passed']


def test_calibration_gate_rejects_collapse_and_weak_value():
    gates={'normalized_delta_min':.003,'interval_low_min':-.003,'maximum_profile_share':.85,'minimum_unique_profiles':3}
    summary={'primary':{'auto_vs_balanced':{'normalized_categories':{'delta':.01,'interval':[-.001,.02]}}},
             'maximum_profile_share':.7,'unique_profiles':4}
    assert v823.eligible(summary,gates)
    summary['unique_profiles']=2;assert not v823.eligible(summary,gates)
    summary['unique_profiles']=4;summary['primary']['auto_vs_balanced']['normalized_categories']['delta']=.001
    assert not v823.eligible(summary,gates)


def test_plan_freezes_v822_and_creates_fresh_scenarios():
    plan=v823.plan()
    assert plan['training'] is False and plan['frozen_v822_checkpoints']==3
    assert plan['development_eligible_families']==['9']
    assert plan['fresh_calibration_drafts']==792 and plan['fresh_holdout_drafts']==212
    assert not plan['auto_promote']
