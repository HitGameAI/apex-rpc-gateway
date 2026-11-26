#!/usr/bin/env python3
"""Public exact-source workspace for one read-only RPC reusable-workflow run."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
MANIFEST=HERE/'rpc-shared-source-pins.json'
REPO='HitGameAI/apex-rpc-gateway'
REF='refs/heads/codex/verify-rpc1-shared-go-ci-20261126'
PARENT='4469574177ce1520f805667e621d6bbe2ac6b216'
WSC='d1e7c62a7b560176007c67aa0ff04679d2727267'

class Rejected(Exception):
    pass

def require(condition,reason):
    if not condition:raise Rejected(reason)

def digest(data):return hashlib.sha256(data).hexdigest()
def git_blob(data):return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()

def command(argv,cwd=None,env=None,reason='command'):
    p=subprocess.run(argv,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=150)
    require(p.returncode==0,reason+'-exit-'+str(p.returncode))
    return p.stdout

def git_env():
    return {'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_TERMINAL_PROMPT':'0','GIT_ALLOW_PROTOCOL':'https'}

def tree_entries(directory,rev):
    raw=command(['/usr/bin/git','-C',str(directory),'ls-tree','-r','-z',rev],env=git_env(),reason='git-tree')
    result={}
    for entry in raw.split(b'\0'):
        if entry:
            spec,path=entry.split(b'\t');mode,kind,oid=spec.decode().split()
            require(kind=='blob','non-blob-source-entry')
            result[path.decode()]={'mode':mode,'git_blob':oid}
    return result

def locks(source):
    return {name:digest((source/name).read_bytes()) for name in ('go.mod','go.sum')}

def context_allowed(env,event):
    return (env.get('GITHUB_REPOSITORY')==REPO and env.get('GITHUB_REPOSITORY_ID')=='1445014240'
      and env.get('GITHUB_ACTOR')=='FJ-Tony' and env.get('GITHUB_EVENT_NAME')=='push'
      and env.get('GITHUB_REF')==REF and env.get('GITHUB_RUN_ATTEMPT')=='1'
      and env.get('RUNNER_ENVIRONMENT')=='github-hosted' and env.get('RUNNER_OS')=='Linux'
      and env.get('RUNNER_ARCH')=='X64' and event.get('created') is True
      and event.get('deleted') is False and event.get('forced') is False
      and event.get('before')=='0'*40 and event.get('after')==env.get('GITHUB_SHA'))

def checkout_binding(source,manifest,expected_head):
    head=command(['/usr/bin/git','-C',str(source),'rev-parse','HEAD'],env=git_env(),reason='checkout-head').decode().strip()
    require(head==expected_head,'checkout-head-mismatch')
    # cat-file preserves actual parent headers even in actions/checkout's shallow clone.
    header=command(['/usr/bin/git','-C',str(source),'cat-file','-p','HEAD'],env=git_env(),reason='checkout-commit').split(b'\n\n',1)[0]
    parents=[line[7:].decode() for line in header.splitlines() if line.startswith(b'parent ')]
    require(parents==[PARENT],'checkout-single-parent')
    actual=tree_entries(source,'HEAD')
    require(set(actual)==set(manifest['rpc_tree'])|set(manifest['new_control_paths']),'checkout-path-set')
    require(all(actual.get(p)==row for p,row in manifest['rpc_tree'].items()),'checkout-original-tree-drift')
    require(locks(source)==manifest['rpc_locks_sha256'],'rpc-lock-drift')
    for path,oid in manifest['rpc_go_files'].items():
        require(git_blob((source/path).read_bytes())==oid,'rpc-working-go-drift')
    return head

def validate_workspace(workfile,source,wsc,go):
    env=dict(os.environ,GOWORK=str(workfile),GOTOOLCHAIN='local',GOENV='off')
    value=json.loads(command([go,'work','edit','-json'],cwd=source,env=env,reason='workspace-json'))
    require(value['Go']=='1.25.0' and not value.get('Replace'),'workspace-contract')
    require(sorted(x['DiskPath'] for x in value['Use'])==sorted([str(source),str(wsc)]),'workspace-use-roots')
    data=command([go,'list','-m','-json','github.com/HitGameAI/apex-wsc'],cwd=source,env=env,reason='workspace-wsc-selection')
    selected=json.loads(data)
    require(selected.get('Main') is True and Path(selected['Dir']).resolve()==wsc.resolve(),'workspace-selected-wsc')
    return {'selected_wsc_is_workspace_main':True,'selected_wsc_version':selected.get('Version'),'workspace_use_count':2}

def project_wsc(bare,destination,manifest):
    require(tree_entries(bare,WSC)==manifest['wsc_tree'],'wsc-full-tree-binding')
    paths=manifest['wsc_projection']
    p=subprocess.Popen(['/usr/bin/git','-C',str(bare),'cat-file','--batch'],env=git_env(),stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    for path,row in sorted(paths.items()):
        require(row['mode']=='100644' and '..' not in Path(path).parts and not Path(path).is_absolute(),'wsc-projection-path')
        p.stdin.write((row['git_blob']+'\n').encode());p.stdin.flush()
        header=p.stdout.readline().split();require(len(header)==3 and header[1]==b'blob','wsc-blob-header')
        body=p.stdout.read(int(header[2]));require(p.stdout.read(1)==b'\n' and git_blob(body)==row['git_blob'],'wsc-blob-hash')
        target=destination/path;target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as f:f.write(body)
    p.stdin.close();require(p.wait(timeout=15)==0,'wsc-batch-exit')
    require(locks(destination)==manifest['wsc_locks_sha256'],'wsc-original-lock-drift')

def stage_path(env):
    run_id=env.get('GITHUB_RUN_ID','')
    require(re.fullmatch(r'[0-9]+',run_id) is not None,'run-id-shape')
    parent=Path(env['RUNNER_TEMP']).resolve(strict=True)
    return parent/('rpc-pr1-shared-workspace-'+run_id+'-1')

def prepare():
    manifest=json.loads(MANIFEST.read_bytes())
    event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_bytes())
    require(context_allowed(os.environ,event),'first-push-context')
    require(sys.platform=='linux' and os.uname().machine=='x86_64','native-linux-amd64')
    source=Path(os.environ['GITHUB_WORKSPACE']).resolve(strict=True)
    checkout_binding(source,manifest,os.environ['GITHUB_SHA'])
    go=shutil.which('go');require(go is not None,'go-missing')
    require(command([go,'version'],reason='go-version').decode().strip()=='go version go1.25.0 linux/amd64','go-toolchain')
    require(all(os.access(p,os.X_OK) for p in ('/usr/bin/git','/usr/bin/sudo','/usr/bin/unshare','/usr/bin/setpriv','/usr/sbin/ip')),'loopback-host-tools')
    require(subprocess.run(['/usr/bin/sudo','-n','/usr/bin/true'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0,'passwordless-sudo')
    stage=stage_path(os.environ);stage.mkdir(mode=0o700)
    bare=stage/'wsc.git';wsc=stage/'wsc';wsc.mkdir(mode=0o700)
    command(['/usr/bin/git','init','--bare',str(bare)],env=git_env(),reason='wsc-bare-init')
    command(['/usr/bin/git','-C',str(bare),'-c','credential.helper=','-c','core.hooksPath=/dev/null','-c','fetch.fsckObjects=true','fetch','--no-tags','--depth=1','https://github.com/HitGameAI/apex-wsc.git',WSC],env=git_env(),reason='wsc-public-exact-fetch')
    require(command(['/usr/bin/git','-C',str(bare),'rev-parse','FETCH_HEAD'],env=git_env()).decode().strip()==WSC,'wsc-fetched-commit')
    require(command(['/usr/bin/git','-C',str(bare),'rev-parse',WSC+'^{tree}'],env=git_env()).decode().strip()==manifest['wsc_tree_oid'],'wsc-fetched-tree')
    project_wsc(bare,wsc,manifest)
    workfile=stage/'go.work'
    workfile.write_text('go 1.25.0\n\nuse (\n\t'+json.dumps(str(source))+'\n\t'+json.dumps(str(wsc))+'\n)\n')
    selected=validate_workspace(workfile,source,wsc,go)
    require(locks(source)==manifest['rpc_locks_sha256'],'rpc-lock-after-workspace')
    with Path(os.environ['GITHUB_ENV']).open('a') as f:
        f.write('GOWORK='+str(workfile)+'\nGOTOOLCHAIN=local\nGOENV=off\n')
    # A literal executable basename in test-flags resolves only after this runtime step.
    with Path(os.environ['GITHUB_PATH']).open('a') as f:f.write(str(HERE)+'\n')
    proof={'schema':1,'run_id':os.environ['GITHUB_RUN_ID'],'head':os.environ['GITHUB_SHA'],'rpc_preview':PARENT,'wsc_commit':WSC,'wsc_tree':manifest['wsc_tree_oid'],'rpc_original_locks':True,'wsc_original_locks':True,'source_mode':'public-exact-git-go-projection','wsc_go_files':sum(p.endswith('.go') for p in manifest['wsc_projection']),'credential_helper_used_for_source':False,'diagnostic_workspace_override_only':True,'formal_wsc_version_claimed':False,**selected}
    (stage/'prepared.json').write_text(json.dumps(proof,sort_keys=True)+'\n')
    print('RPC_SHARED_WORKSPACE_PREPARED='+json.dumps(proof,sort_keys=True))

def verify():
    manifest=json.loads(MANIFEST.read_bytes());source=Path(os.environ['GITHUB_WORKSPACE']).resolve(strict=True)
    checkout_binding(source,manifest,os.environ['GITHUB_SHA'])
    stage=stage_path(os.environ);wsc=stage/'wsc';workfile=stage/'go.work'
    require(os.environ.get('GOWORK')==str(workfile),'workspace-env-retained')
    selected=validate_workspace(workfile,source,wsc,shutil.which('go'))
    require(locks(wsc)==manifest['wsc_locks_sha256'],'wsc-lock-after-tests')
    for path,row in manifest['wsc_projection'].items():require(git_blob((wsc/path).read_bytes())==row['git_blob'],'wsc-source-after-tests')
    require((source/'coverage.txt').is_file() and (source/'coverage.txt').stat().st_size>0,'coverage-file-missing')
    proof=json.loads((stage/'prepared.json').read_bytes())
    proof.update(accepted=True,rpc_original_locks_after=True,wsc_original_locks_after=True,all_pinned_source_blobs_after=True,local_coverage_present=True,**selected)
    # Future post-actions must not inherit a path to a removed go.work.
    with Path(os.environ['GITHUB_ENV']).open('a') as f:f.write('GOWORK=off\n')
    shutil.rmtree(stage)
    proof['temporary_public_source_workspace_removed']=not stage.exists()
    print('RPC_SHARED_WORKSPACE_RESULT='+json.dumps(proof,sort_keys=True))

if __name__=='__main__':
    os.umask(0o077)
    try:
        require(len(sys.argv)==2 and sys.argv[1] in ('prepare','verify'),'phase-argument')
        prepare() if sys.argv[1]=='prepare' else verify()
    except Rejected as e:
        print('RPC_SHARED_WORKSPACE_REJECTED='+json.dumps({'phase':sys.argv[1] if len(sys.argv)>1 else 'unknown','reason':str(e)},sort_keys=True))
        raise SystemExit(1)
    except (OSError,ValueError,KeyError,subprocess.SubprocessError) as e:
        print('RPC_SHARED_WORKSPACE_REJECTED='+json.dumps({'phase':sys.argv[1] if len(sys.argv)>1 else 'unknown','reason':'unexpected-'+type(e).__name__},sort_keys=True))
        raise SystemExit(1)
