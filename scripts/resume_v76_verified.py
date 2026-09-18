"""Audited V7.6 resume: seven unrelated service changes only, exact old hash."""
import argparse
import hashlib
import importlib.abc
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import draft_v76_distillation as experiment
from scripts import draft_ml_v7_run as original

COMMIT='7700da388b6d9de1dbcd3b20851ae2d2ca28af02'
EXPECTED='284a8fc11d79d7ab448647c3740fae9fc1d0123845098eb3ae182df4e26102de'
UNRELATED=('core/matchup_mc.py','core/season_mc.py','web/backend/services/forecast_history.py',
 'web/backend/services/matchup_engine.py','web/backend/services/season.py',
 'web/backend/services/trades.py','web/backend/services/waivers.py')
BLOCKED={p[:-3].replace('/','.') for p in UNRELATED}
ORIGINAL_INITIALIZER=experiment.initialize


def guarded_initialize(*args):
    install()
    return ORIGINAL_INITIALIZER(*args)


class DependencyGuard(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname in BLOCKED:
            raise ImportError('Audited unrelated module became an experiment dependency: '+fullname)
        return None


def verified_fingerprint(config):
    snapshot,teacher,_=original.paths(config)
    sources=list((ROOT/'web/backend/services').rglob('*.py'))+list((ROOT/'core').rglob('*.py'))
    sources += [ROOT/'scripts/draft_ml_v7_run.py',snapshot,teacher/'genomes.json',teacher/'manifest.json']
    digest=hashlib.sha256(json.dumps(config,sort_keys=True).encode())
    for path in sorted(sources):
        relative=path.relative_to(ROOT)
        if relative.as_posix() in UNRELATED:
            data=subprocess.check_output(['git','show',COMMIT+':'+relative.as_posix()],cwd=ROOT)
            # Original Windows working tree had CRLF. This exactly reconstructs
            # the saved fingerprint, not an approximate compatibility assertion.
            data=data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
        else:
            data=path.read_bytes()
        digest.update(str(relative).encode()); digest.update(data)
    return digest.hexdigest()


def install():
    if BLOCKED.intersection(sys.modules):
        raise RuntimeError('An excluded service is already imported')
    sys.meta_path.insert(0,DependencyGuard())
    experiment.initialize=guarded_initialize
    experiment.base.fingerprint=verified_fingerprint
    config,settings,out=experiment.configuration()
    if experiment.identity(config,settings)!=EXPECTED:
        raise ValueError('Other experiment changes detected; verified resume refused')
    return out


def check(out):
    journal=json.loads((out/'run-state.json').read_text())
    if journal['provenance']!=EXPECTED or 'generate' not in journal['completed']:
        raise ValueError('Unexpected saved experiment')
    for stage in journal['completed']:
        for name,digest in journal['checksums'][stage].items():
            if experiment.sha(out/name)!=digest:
                raise ValueError('Saved artifact changed: '+name)
    return journal


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--stage',choices=['train','validation','holdout'])
    parser.add_argument('--provenance')
    args=parser.parse_args()
    out=install()
    if args.stage:
        if args.provenance!=EXPECTED: raise ValueError('Invalid stage provenance')
        experiment.phase(args.stage,EXPECTED)
        return
    journal=check(out)
    if not args.execute:
        print(json.dumps(dict(verified=True,provenance=EXPECTED,completed=journal['completed'],excluded_modules=list(BLOCKED)),indent=2))
        return
    experiment.save(out/('compatibility-resume-'+str(time.time_ns())+'.json'),dict(
        provenance=EXPECTED,reference_commit=COMMIT,excluded_files={p:experiment.sha(ROOT/p) for p in UNRELATED},
        wrapper_sha256=experiment.sha(Path(__file__)),previous_status=json.loads((out/'status.json').read_text()),
        rationale='Exact original identity recovered with only seven unrelated modules restored in hashing; their import is prohibited.'))
    real_popen=subprocess.Popen
    class verified_child(real_popen):
        def __init__(self,args,*positional,**kwargs):
            if isinstance(args,list) and len(args)>2 and args[2]==str(ROOT/'scripts/draft_v76_distillation.py') and '--stage' in args:
                args=list(args); args[2]=str(Path(__file__))
            super().__init__(args,*positional,**kwargs)
    subprocess.Popen=verified_child
    try: experiment.run()
    finally: subprocess.Popen=real_popen


if __name__=='__main__': main()
