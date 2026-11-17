#!/usr/bin/env python3
"""Synthetic methodology checks; these are not experiment results."""
from pathlib import Path
import tempfile, subprocess, csv, json, gzip, math
script=Path(__file__).resolve().with_name('analyze_results.py')
with tempfile.TemporaryDirectory(prefix='htree-analysis-check-') as td:
    root=Path(td);res=root/'results';dataset=res/'patched-n100';dataset.mkdir(parents=True)
    rows=[]
    base={'kernel':'5.4.214-htree1','pass':0,'queries':2,'positive':1,'negative':1,'errors':0,'mean_ns':30,'p50_ns':20,'p95_ns':40,'cache_mode':'warmdir','digest':'same'}
    for rep in range(2):
      for j,label in enumerate(['binary','hybrid4']):
        trial=rep*2+j;elapsed=[[200,160],[400,440]][rep][j]
        row=dict(base,trial=trial,round=rep,label=label,seed=7+rep,elapsed_ns=elapsed);rows.append(row)
        prefix=dataset/('trial_%04d_%s_warmdir'%(trial,label))
        Path(str(prefix)+'.json').write_text(json.dumps({'returncode':0,'query_seed':7+rep}))
        Path(str(prefix)+'.policy').write_text('search=%d limit=4 profile_during_trial=0\n'%(0 if label=='binary' else 2))
        Path(str(prefix)+'.stats').write_text('find=0 nodes=0 comparisons=0 mismatches=0 leaf_errors=0\n')
        lp=Path(str(prefix)+'.latencies.csv'+('.gz' if trial==1 else ''))
        opener=gzip.open if lp.suffix=='.gz' else open
        with opener(lp,'wt',newline='') as f:
          w=csv.writer(f);w.writerow(['trial','pass','index','expected_exists','latency_ns','name']);w.writerows([[trial,0,0,1,20,'file'],[trial,0,1,0,40,'absent']])
    with (dataset/'summary.csv').open('w',newline='') as f:
      w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    pdir=res/'profile-n100';pdir.mkdir();prefix=pdir/'trial_0000_hybrid4_warmdir'
    Path(str(prefix)+'.json').write_text(json.dumps({'returncode':0,'condition':{'label':'hybrid4'},'cache_mode':'warmdir'}))
    Path(str(prefix)+'.policy').write_text('search=2 limit=4 profile_during_trial=1')
    Path(str(prefix)+'.stats').write_text('find=2 dx_lookup=2 probe=2 nodes=2 count_sum=8 binary_nodes=0 linear_nodes=2 comparisons=6 leaf_blocks=2 leaf_entries=10 leaf_errors=0 mismatches=0 count_3_4=2')
    with Path(str(prefix)+'.csv').open('w',newline='') as f:
      w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerow(rows[1])
    (res/'micro.csv').write_text('round,count,mode,ns_per_search\n0,8,binary,2\n1,8,binary,4\n0,8,linear,1\n1,8,linear,3\n')
    out=root/'out'
    p=subprocess.run(['python3',str(script),'--results',str(res),'--output',str(out),'--latencies'],capture_output=True,text=True)
    assert p.returncode==0,(p.stdout,p.stderr)
    r=json.loads((out/'analysis_summary.json').read_text())
    assert len(r['timing_summary'])==2
    assert all(x['loop_ns_per_query_median']==150 for x in r['timing_summary'])
    assert math.isclose(r['paired_summary'][0]['policy_over_binary_median'],.95)
    assert r['profile_summary'][0]['comparisons_per_node']==3
    assert r['profile_summary'][0]['leaf_entries_per_query']==5
    assert len(list(csv.DictReader((out/'query_kind_trials.csv').open())))==8
    first=dataset/'trial_0001_hybrid4_warmdir.policy';first.write_text('search=2 limit=4 profile_during_trial=1')
    p=subprocess.run(['python3',str(script),'--results',str(res),'--output',str(out)],capture_output=True,text=True)
    assert p.returncode==1
    r=json.loads((out/'analysis_summary.json').read_text())
    assert any(i['code']=='profiling_during_timing' for i in r['issues'])
    assert next(x for x in r['timing_summary'] if x['label']=='hybrid4')['trials']==1
    print('analysis self-check passed: paired ratios, primary metric, gzip splits, profile counters, exclusion of profiled timing')
