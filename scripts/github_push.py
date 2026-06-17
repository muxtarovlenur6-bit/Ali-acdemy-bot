import base64
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
GIT_CONFIG = ROOT / '.git' / 'config'
GIT_HEAD = ROOT / '.git' / 'HEAD'

if not GIT_CONFIG.exists() or not GIT_HEAD.exists():
    raise SystemExit('.git metadata missing')

with open(GIT_CONFIG, 'r', encoding='utf-8') as f:
    config_text = f.read()

remote_match = re.search(r'\[remote \"origin\"\][^\n]*\n\s*url\s*=\s*(.*)', config_text)
if not remote_match:
    raise SystemExit('origin remote not found in .git/config')

remote_url = remote_match.group(1).strip()

with open(GIT_HEAD, 'r', encoding='utf-8') as f:
    head = f.read().strip()

branch = 'main'
if head.startswith('ref: '):
    branch = head.split('ref: ')[1].strip().split('/')[-1]

parsed = urllib.parse.urlparse(remote_url)
if parsed.scheme not in ('http', 'https'):
    raise SystemExit('Unsupported remote URL scheme')

repo_path = parsed.path.lstrip('/')
if repo_path.endswith('.git'):
    repo_path = repo_path[:-4]

token = None
if parsed.password:
    token = urllib.parse.unquote(parsed.password)
elif os.getenv('GITHUB_TOKEN'):
    token = os.getenv('GITHUB_TOKEN')

if not token:
    raise SystemExit('GitHub token not found. Set it in the remote URL or GITHUB_TOKEN environment variable.')

repo = repo_path

print(f'Repo: {repo}')
print(f'Branch: {branch}')

headers = {
    'Authorization': f'token {token}',
    'Accept': 'application/vnd.github+json',
    'User-Agent': 'github-push-script',
}


def request_json(url, data=None, method='GET'):
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode('utf-8'), resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='ignore')
        return body, exc.code


def github_get(url):
    body, status = request_json(url)
    if status == 404:
        return None
    if status >= 400:
        raise SystemExit(f'GET {url} failed: {status}\n{body}')
    return json.loads(body)


def github_put(url, payload):
    data = json.dumps(payload).encode('utf-8')
    body, status = request_json(url, data=data, method='PUT')
    if status not in (200, 201):
        raise SystemExit(f'PUT {url} failed: {status}\n{body}')
    return json.loads(body)


ignore_dirs = {'venv', '.git', '__pycache__', '.idea', '.vscode', 'dist', 'build'}
ignore_files = {'.env', 'davomat.db'}
ignore_extensions = {'.pyc', '.pyo', '.pyd', '.db', '.db-journal', '.sqlite', '.sqlite3', '.log', '.tmp'}

files = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in ignore_dirs and not d.startswith('.')]
    for fname in filenames:
        if fname.startswith('.') and fname != '.gitignore':
            continue
        if fname in ignore_files:
            continue
        if os.path.splitext(fname)[1] in ignore_extensions:
            continue
        rel = os.path.relpath(os.path.join(dirpath, fname), ROOT).replace('\\', '/')
        if rel.startswith('venv/') or rel.startswith('.git/'):
            continue
        files.append(rel)

files.sort()
print(f'Local files to push: {len(files)}')

commit_message = 'Deploy bot files from local machine'

for path in files:
    print('Uploading', path)
    url = f'https://api.github.com/repos/{repo}/contents/{urllib.parse.quote(path, safe="/")}?ref={branch}'
    existing = github_get(url)
    content = (ROOT / path).read_bytes()
    encoded = base64.b64encode(content).decode('ascii')
    payload = {
        'message': commit_message,
        'content': encoded,
        'branch': branch,
    }
    if existing and isinstance(existing, dict) and existing.get('sha'):
        payload['sha'] = existing['sha']
    response = github_put(url, payload)
    print('Result:', response.get('content', {}).get('path'))

print('Push complete.')
