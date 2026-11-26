#!/usr/bin/env python3
"""Draft public-only Linux pair check; no private source or App authentication."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PUBLIC = {'apex-bizerror', 'apex-bot', 'apex-casbin', 'apex-cos', 'apex-namesilo', 'apex-rpc-gateway', 'apex-swagger', 'apex-toolbox', 'apex-wsc'}
PUBLIC_MODULES = {'github.com/HitGameAI/' + name for name in PUBLIC} | {
    'github.com/HitGameAI/apex-bizerror/pbx', 'github.com/HitGameAI/apex-bizerror/gwx'}
PINS = {
    'wsc': ('d1e7c62a7b560176007c67aa0ff04679d2727267', '08251d261dd2e3c1b80e259eeac387613e965c1a'),
    'rpc': ('4469574177ce1520f805667e621d6bbe2ac6b216', '32dc36f7250b50a54ab6aa19396960b39d7b482b'),
}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def call(argv, env=None, cwd=None):
    return subprocess.run(argv, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=420)

def context_allowed(event, env):
    return (env.get('GITHUB_REPOSITORY') == 'HitGameAI/apex-rpc-gateway'
            and env.get('GITHUB_REPOSITORY_ID') == '1445014240'
            and env.get('GITHUB_ACTOR') == 'FJ-Tony'
            and env.get('GITHUB_EVENT_NAME') == 'push'
            and env.get('GITHUB_REF') == 'refs/heads/codex/verify-public-wsc11-rpc1-linux-20261126'
            and env.get('GITHUB_RUN_ATTEMPT') == '1'
            and env.get('GITHUB_ACTIONS') == 'true'
            and env.get('RUNNER_ENVIRONMENT') == 'github-hosted'
            and env.get('RUNNER_OS') == 'Linux' and env.get('RUNNER_ARCH') == 'X64'
            and event.get('created') is True and event.get('deleted') is False
            and event.get('forced') is False and event.get('before') == '0' * 40)

def isolated_worker_allowed(uid, gid, groups, capabilities, no_new_privileges,
                            host_namespace, worker_namespace, interfaces):
    return (uid == 65534 and gid == 65534 and groups == [] and capabilities == 0
            and no_new_privileges == '1' and bool(host_namespace) and bool(worker_namespace)
            and host_namespace != worker_namespace and sorted(interfaces) == ['lo'])

def store(path, doc):
    path.write_text(json.dumps(doc, indent=2) + '\n')
    path.chmod(0o644)

def locked_sources(workspace):
    result = {}
    for role, (commit, tree) in PINS.items():
        source = workspace / role
        for query, expected in [('HEAD', commit), ('HEAD^{tree}', tree)]:
            actual = call(['git', '-C', str(source), 'rev-parse', query])
            if actual.returncode or actual.stdout.decode().strip() != expected:
                raise RuntimeError('source-git-binding-failed')
        result[role] = {name: sha((source / name).read_bytes()) for name in ['go.mod', 'go.sum']}
    return result

def prepare(workspace, scratch):
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    if not context_allowed(event, os.environ):
        raise RuntimeError('wrong-first-push-context')
    if sys.platform != 'linux' or os.uname().machine != 'x86_64':
        raise RuntimeError('native-linux-amd64-required')
    if any(not os.access(path, os.X_OK) for path in
           ['/usr/bin/python3', '/usr/bin/unshare', '/usr/bin/setpriv', '/usr/sbin/ip', '/usr/bin/sudo', '/usr/bin/gcc']):
        raise RuntimeError('required-ubuntu-tool-missing')
    if call(['/usr/bin/sudo', '-n', '/usr/bin/true']).returncode:
        raise RuntimeError('passwordless-sudo-unavailable')
    scratch.mkdir(mode=0o755)
    for name in ['home', 'tmp', 'gomodcache', 'gocache', 'evidence']:
        (scratch / name).mkdir(mode=0o755)
    upload = Path(str(scratch) + '-json')
    upload.mkdir(mode=0o755)
    store(upload / 'binding.json', {'schema': 1, 'run_id': os.environ['GITHUB_RUN_ID'],
          'attempt': 1, 'diagnostic_sha': os.environ['GITHUB_SHA'], 'pins': PINS})
    go = shutil.which('go')
    if not go:
        raise RuntimeError('go-missing')
    env = {'PATH': str(Path(go).parent) + ':/usr/bin:/bin', 'HOME': str(scratch / 'home'),
           'TMPDIR': str(scratch / 'tmp'), 'GOPATH': str(scratch / 'gopath'),
           'GOMODCACHE': str(scratch / 'gomodcache'), 'GOCACHE': str(scratch / 'gocache'),
           'GOTOOLCHAIN': 'local', 'GOENV': 'off', 'GOWORK': 'off', 'GOAUTH': 'off',
           'GOVCS': '*:off', 'GOFLAGS': '-mod=readonly', 'CGO_ENABLED': '1', 'GOOS': 'linux', 'GOARCH': 'amd64',
           'GOPROXY': 'https://proxy.golang.org', 'GOSUMDB': 'sum.golang.org',
           'GONOPROXY': 'none', 'GONOSUMDB': 'none', 'LANG': 'C.UTF-8'}
    if call([go, 'version'], env).stdout.decode().strip() != 'go version go1.25.0 linux/amd64':
        raise RuntimeError('wrong-go-version')
    original_workspace = workspace
    locks = locked_sources(original_workspace)
    # A different UID must not depend on traversing /home/runner or RUNNER_TEMP.
    # These are fixed public checkouts, not any existing business workspace.
    workspace = scratch / 'sources'
    workspace.mkdir(mode=0o755)
    for role in PINS:
        for root, dirs, files in os.walk(original_workspace / role, followlinks=False):
            dirs[:] = [d for d in dirs if d not in ['.git', '.github', '.vscode']]
            if any((Path(root) / name).is_symlink() for name in dirs + files):
                raise RuntimeError('public-source-symlink-not-admitted')
        shutil.copytree(original_workspace / role, workspace / role,
                        ignore=shutil.ignore_patterns('.git', '.github', '.vscode'))
    (scratch / 'controls').mkdir(mode=0o755)
    for name in ['proof.py', 'tests.json']:
        shutil.copyfile(HERE / name, scratch / 'controls' / name)
    sums = {}
    for role in PINS:
        for line in (workspace / role / 'go.sum').read_text().splitlines():
            module, version, digest = line.split()
            if module.startswith('github.com/HitGameAI/'):
                if module not in PUBLIC_MODULES:
                    raise RuntimeError('unapproved-organization-module')
                sums.setdefault((module, version.removesuffix('/go.mod')), {})['mod' if version.endswith('/go.mod') else 'zip'] = digest
    module_checks = []
    for (module, version), expected in sorted(sums.items()):
        proc = call([go, 'mod', 'download', '-json', module + '@' + version], env, scratch)
        if proc.returncode:
            raise RuntimeError('fixed-public-module-prefetch-failed')
        downloaded = json.loads(proc.stdout)
        if expected.get('zip', downloaded.get('Sum')) != downloaded.get('Sum') or expected.get('mod', downloaded.get('GoModSum')) != downloaded.get('GoModSum'):
            raise RuntimeError('public-module-lock-h1-mismatch')
        module_checks.append({'module': module, 'version': version,
              'canonical_zip_h1': downloaded.get('Sum'), 'canonical_mod_h1': downloaded.get('GoModSum'),
              'original_zip_h1_present': 'zip' in expected, 'original_mod_h1_present': 'mod' in expected,
              'lock_h1_matches': True, 'native_sumdb_enabled': True})
    # Every other organization path is denied network/VCS fallback. Public pins above are cached.
    env['GONOPROXY'] = 'github.com/HitGameAI/*'
    env['GONOSUMDB'] = 'github.com/HitGameAI/*'
    modfile = scratch / 'rpc-diagnostic.mod'
    shutil.copyfile(workspace / 'rpc/go.mod', modfile)
    shutil.copyfile(workspace / 'rpc/go.sum', scratch / 'rpc-diagnostic.sum')
    proc = call([go, 'mod', 'edit', '-modfile=' + str(modfile), '-replace=github.com/HitGameAI/apex-wsc=' + str(workspace / 'wsc')], env, workspace / 'rpc')
    if proc.returncode:
        raise RuntimeError('diagnostic-source-map-failed')
    for role in PINS:
        args = [go, 'mod', 'download']
        if role == 'rpc':
            args.append('-modfile=' + str(modfile))
        proc = call(args, env, workspace / role)
        if proc.returncode:
            raise RuntimeError('public-dependency-stage-failed')
    if locks != locked_sources(original_workspace):
        raise RuntimeError('original-lock-mutated')
    if locks != {role: {name: sha((workspace / role / name).read_bytes()) for name in ['go.mod', 'go.sum']} for role in PINS}:
        raise RuntimeError('staged-original-lock-mutated')
    env.update(GOPROXY='off', GOSUMDB='off')
    plan = {'schema': 1, 'go': go, 'env': env, 'locks': locks, 'workspace': str(workspace),
            'modfile': str(modfile), 'host_network_namespace': os.readlink('/proc/self/ns/net'),
            'run_id': os.environ['GITHUB_RUN_ID'], 'attempt': 1, 'diagnostic_sha': os.environ['GITHUB_SHA'],
            'pins': PINS, 'public_organization_module_versions': len(sums),
            'public_organization_h1_checks': module_checks,
            'diagnostic_only_local_wsc_source_mapping': True,
            'new_release_or_published_module_version_claimed': False}
    store(scratch / 'plan.json', plan)
    store(scratch / 'evidence/source.json', {k: v for k, v in plan.items() if k not in ['env', 'go', 'workspace', 'modfile']})

def run(scratch):
    plan = json.loads((scratch / 'plan.json').read_text())
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    # sysfs can still describe the host namespace after unshare --net. Query the
    # current network namespace through the socket API instead of the host mount.
    interfaces = [name for _, name in socket.if_nameindex()]
    if not isolated_worker_allowed(os.getuid(), os.getgid(), os.getgroups(),
            int(status['CapEff'].strip(), 16), status['NoNewPrivs'].strip(),
            plan['host_network_namespace'], os.readlink('/proc/self/ns/net'), interfaces):
        raise RuntimeError('isolated-worker-contract-failed')
    env = plan['env']
    workspace = Path(plan['workspace'])
    tests = json.loads((HERE / 'tests.json').read_text())
    names = sorted({name for group in tests.values() for name in group})
    commands = {
        'wsc': [plan['go'], 'test', '-mod=readonly', '-buildvcs=false', '-count=1', '-timeout=180s', '-json', '-run', '^(' + '|'.join(names) + ')$'] + list(tests),
        'rpc': [plan['go'], 'test', '-mod=readonly', '-modfile=' + plan['modfile'], '-buildvcs=false', '-count=1', '-timeout=180s', '-json', './...'],
    }
    rows = []
    for role, argv in commands.items():
        proc = call(argv, env, workspace / role)
        parents = []
        for line in proc.stdout.splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            name = item.get('Test', '')
            if item.get('Action') in ['pass', 'fail', 'skip'] and re.fullmatch(r'Test[A-Za-z0-9_]+', name):
                package = item.get('Package', '')
                if package.startswith('github.com/HitGameAI/apex-' + ('wsc' if role == 'wsc' else 'rpc-gateway')):
                    parents.append({'package': package, 'test': name, 'action': item['Action']})
        rows.append({'role': role, 'exit_code': proc.returncode, 'parents': parents,
                     'stdout_sha256': sha(proc.stdout), 'stderr_sha256': sha(proc.stderr)})
    locks_after = {role: {name: sha((workspace / role / name).read_bytes()) for name in ['go.mod', 'go.sum']} for role in PINS}
    expected = {('github.com/HitGameAI/apex-wsc/' + pkg[2:], name) for pkg, group in tests.items() for name in group}
    actual = {(item['package'], item['test']) for item in rows[0]['parents'] if item['action'] == 'pass'}
    success = (all(row['exit_code'] == 0 and row['parents'] and all(t['action'] != 'fail' for t in row['parents']) for row in rows)
               and actual == expected and len(rows[0]['parents']) == len(expected)
               and any(t['action'] == 'pass' for t in rows[1]['parents']) and locks_after == plan['locks'])
    store(scratch / 'evidence/tests.json', {'schema': 1, 'run_id': plan['run_id'], 'attempt': 1,
          'diagnostic_sha': plan['diagnostic_sha'], 'source_pins': PINS, 'go': 'go1.25.0',
          'goos': 'linux', 'goarch': 'amd64', 'cgo': 1, 'rows': rows, 'pass': success,
          'original_locks_unchanged': locks_after == plan['locks'], 'loopback_only': True,
          'worker_uid': os.getuid(), 'capabilities': 0, 'no_new_privileges': True,
          'credentials_inherited': False, 'raw_output_persisted': False})
    if not success:
        raise SystemExit(1)

def cleanup(scratch):
    if scratch.is_symlink():
        raise RuntimeError('scratch-must-not-be-a-symlink')
    scratch.mkdir(mode=0o755, exist_ok=True)
    evidence = scratch / 'evidence'
    evidence.mkdir(mode=0o755, exist_ok=True)
    upload = Path(str(scratch) + '-json')
    if upload.is_symlink() or (upload.exists() and upload.stat().st_uid == 65534):
        raise RuntimeError('upload-directory-not-parent-owned')
    upload.mkdir(mode=0o755, exist_ok=True)
    for child in evidence.iterdir():
        if child.name not in ['source.json', 'tests.json', 'failure.json'] or child.is_symlink() or not child.is_file() or child.stat().st_nlink != 1 or child.stat().st_size > 1024 * 1024:
            raise RuntimeError('unapproved-evidence-member')
        value = json.loads(child.read_text())
        if not isinstance(value, dict) or value.get('schema') != 1:
            raise RuntimeError('invalid-evidence-schema')
        target = upload / child.name
        if target.exists() or target.is_symlink():
            raise RuntimeError('upload-member-already-exists')
        store(target, value)
    shutil.rmtree(scratch)
    store(upload / 'cleanup.json', {'schema': 1, 'public_staged_sources_and_module_cache_removed': True,
          'only_json_evidence_retained': True, 'upload_directory_outside_worker_scratch': True})

def record_failure(scratch, phase, error):
    evidence = scratch / 'evidence'
    if scratch.is_symlink() or not evidence.is_dir() or evidence.is_symlink():
        return
    if isinstance(error, subprocess.TimeoutExpired):
        category = 'command-timeout'
    elif isinstance(error, RuntimeError) and re.fullmatch(r'[a-z0-9-]+', str(error)):
        category = str(error)
    else:
        category = {OSError: 'filesystem-or-process-error', ValueError: 'invalid-json-or-metadata'}.get(type(error), 'control-error')
    store(evidence / 'failure.json', {'schema': 1, 'pass': False, 'phase': phase,
          'category': category, 'raw_output_persisted': False})

if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] not in ['prepare', 'run', 'cleanup']:
        raise SystemExit('expected prepare|run|cleanup workspace scratch')
    mode, workspace, scratch = sys.argv[1], Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    if mode == 'run':
        expected = os.environ.get('PUBLIC_PAIR_SCRATCH', '')
    else:
        run_id = os.environ.get('GITHUB_RUN_ID', '')
        if not re.fullmatch(r'[0-9]+', run_id):
            raise SystemExit('missing-run-identity')
        expected = '/tmp/public-wsc-rpc-pair-' + run_id + '-1'
    if str(scratch) != expected:
        raise SystemExit('wrong-scratch-root')
    try:
        if mode == 'prepare':
            prepare(workspace, scratch)
        elif mode == 'run':
            run(scratch)
        else:
            cleanup(scratch)
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        record_failure(scratch, mode, error)
        print(json.dumps({'phase': mode, 'result': 'failed'}))
        raise SystemExit(1)
