#!/usr/bin/env python3
"""Sync Surge category lists and the two original VPSDance AI lists. Standard library only."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, unquote
from urllib.request import Request, urlopen
import json
from http.client import IncompleteRead
import os
import re
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
BLACKMATRIX = 'blackmatrix7/ios_rule_script'
AI = 'VPSDance/ai-proxy-rules'
# These README links are known to be absent upstream. Report, never silently skip.
MISSING = {'RemoteDesktop', 'ChemeQuations', 'Zoom'}
FILENAMES = {'AdGuardSDNSFilter': 'AdGuardSDNSFilter_All.list',
             'EasyPrivacy': 'EasyPrivacy_All.list'}


def fetch(url):
    headers = {'User-Agent': 'surge-rules-sync'}
    if url.startswith('https://api.github.com/') and os.environ.get('GITHUB_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code == 404 or attempt == 2:
                raise
        except (OSError, EOFError, IncompleteRead):
            if attempt == 2:
                raise
        time.sleep(1)


def commit(repo, branch):
    sha = json.loads(fetch(f'https://api.github.com/repos/{repo}/commits/{branch}'))['sha']
    if not re.fullmatch('[a-f0-9]{40}', sha):
        raise ValueError('Invalid upstream commit')
    return sha


def raw(repo, sha, path):
    return fetch(f'https://raw.githubusercontent.com/{repo}/{sha}/{quote(path, safe="/")}')


def categories(readme):
    result, current, active = {}, None, False
    for line in readme.splitlines():
        if re.match(r'^##\s+分类\s*$', line):
            active = True
        elif active and re.match(r'^#{1,2}\s', line):
            break
        elif active:
            heading = re.match(r'^\|\s*[^|\[\]]*?([A-Za-z][A-Za-z0-9_-]*)\s*\|(?:\s*\|)+\s*$', line)
            if heading:
                current = heading[1]
                if current in result:
                    raise ValueError('Duplicate category: ' + current)
                result[current] = []
            for directory in re.findall(r'https://github\.com/blackmatrix7/ios_rule_script/tree/[^/]+/rule/Surge/([^\s)]+)', line):
                directory = unquote(directory).rstrip('/')
                if not current or any(p in ('', '.', '..') for p in directory.split('/')):
                    raise ValueError('Invalid README link: ' + directory)
                if directory not in result[current]:
                    result[current].append(directory)
    if not result or any(not dirs for dirs in result.values()):
        raise ValueError('No complete category table found')
    # Keep the two media groups. IPTV-only sources are moved, not discarded.
    media = result.pop('Media', [])
    for directory, target in [('IPTVMainland', 'MainlandMedia'), ('IPTVOther', 'GlobalMedia')]:
        if directory in media and directory not in result[target]:
            result[target].append(directory)
    # Exclude a few known non-category sources; no cross-category rule filtering.
    for name, excluded in {'MainlandMedia': {'ChinaMax'}, 'Advertising': {'Direct'},
                           'Other': {'Lan', 'AdGuardSDNSFilter/Direct'}}.items():
        result[name] = [d for d in result[name] if d not in excluded]
    return result


def rules(data):
    lines = [s.strip() for s in data.decode('utf-8-sig').splitlines()
             if s.strip() and not s.lstrip().startswith(('#', '//', ';'))]
    if not lines or any(not re.match(r'(?:DOMAIN(?:-SUFFIX|-KEYWORD)?|IP-CIDR6?|IP-ASN|PROCESS-NAME|USER-AGENT|URL-REGEX|AND|OR|NOT),.+', s) for s in lines):
        raise ValueError('Empty or unsupported rule content')
    return lines


def main():
    bm_sha, ai_sha = commit(BLACKMATRIX, 'master'), commit(AI, 'main')
    groups = categories(raw(BLACKMATRIX, bm_sha, 'rule/Surge/README.md').decode())
    directories = sorted({d for dirs in groups.values() for d in dirs})

    def download(directory):
        filename = FILENAMES.get(directory, directory.rsplit('/', 1)[-1] + '.list')
        try:
            return directory, rules(raw(BLACKMATRIX, bm_sha, f'rule/Surge/{directory}/{filename}'))
        except HTTPError as exc:
            if exc.code != 404 or directory not in MISSING:
                raise
            print('WARNING: upstream missing:', directory, flush=True)
            return directory, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        sources = {}
        for i, (directory, entries) in enumerate(pool.map(download, directories), 1):
            sources[directory] = entries
            if i % 100 == 0:
                print(f'Downloaded {i}/{len(directories)} sources', flush=True)
    outputs = {}
    for name, dirs in groups.items():
        missing = [d for d in dirs if sources[d] is None]
        entries = list(dict.fromkeys(s for d in dirs for s in (sources[d] or [])))
        # The broad Alibaba Cloud suffix would send domestic OSS traffic to Global.
        if name == 'Global':
            entries = [s for s in entries if s != 'DOMAIN-SUFFIX,aliyuncs.com']
        if not entries:
            raise ValueError('Empty category: ' + name)
        header = f'# Source: https://github.com/{BLACKMATRIX}\n# Commit: {bm_sha}\n'
        if missing:
            header += '# INCOMPLETE: missing sources: ' + ', '.join(missing) + '\n'
        outputs[name + '.list'] = (header + '\n'.join(entries) + '\n').encode()
    for name in ('OpenAI', 'Anthropic'):
        content = raw(AI, ai_sha, f'rules/surge/{name.lower()}.list')
        rules(content)
        outputs[name + '.list'] = content  # Preserve upstream bytes, including comments.
    # Only replace the directory after every download succeeds.
    dest = ROOT/'rules'
    with tempfile.TemporaryDirectory(prefix='.sync-', dir=ROOT) as td:
        stage, backup = Path(td)/'rules', Path(td)/'previous'
        stage.mkdir()
        for name, content in outputs.items():
            (stage/name).write_bytes(content)
        if dest.exists():
            dest.rename(backup)
        try:
            stage.rename(dest)
        except BaseException:
            if backup.exists():
                backup.rename(dest)
            raise
    print(f'Synced {len(outputs)} lists. blackmatrix7={bm_sha}; VPSDance={ai_sha}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Sync failed; previous rules retained: {exc}', file=sys.stderr)
        raise SystemExit(1)
