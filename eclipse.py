"""Catalog, constrained downloads and journaled, reversible file installation."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import ssl
from functools import lru_cache
import subprocess
import threading
import unicodedata
import urllib.parse
import urllib.request

SOURCE = 'https://www.steamdeckbase.org/optimization'
FILE_HOST = 'file.steamdeckbase.org'
LIMIT = 16 * 1024**3
CA_BUNDLES = (
    '/etc/ssl/certs/ca-certificates.crt',  # SteamOS / Arch
    '/etc/ca-certificates/extracted/tls-ca-bundle.pem',
    '/etc/pki/tls/certs/ca-bundle.crt',
    '/etc/ssl/cert.pem',
)


@lru_cache(maxsize=1)
def https_context():
    """Decky's embedded Python may point OpenSSL at a nonexistent build-time CA path."""
    context = ssl.create_default_context()
    for filename in (*CA_BUNDLES, str(Path(__file__).parent/'certs/cacert.pem')):
        if Path(filename).is_file():
            try:
                context.load_verify_locations(cafile=filename)
            except (OSError, ssl.SSLError):
                continue
    return context


def game_key(name):
    # Exact title matching after punctuation/case normalization, never fuzzy matching.
    name = name.replace('™', '').replace('®', '').replace('©', '')
    return ''.join(c for c in unicodedata.normalize('NFKD', name).casefold()
                   if c.isalnum() and not unicodedata.combining(c))


def is_steam_tool(name, root):
    """Exclude compatibility runtimes without hiding games that contain 'Proton'."""
    name = name.strip()
    patterns = (
        r'Proton(?:\s*-?\s*(?:Experimental|Hotfix|Next|Bleeding Edge|EasyAntiCheat Runtime|BattlEye Runtime|\d+(?:\.\d+)*(?:-\d+)?)(?:\s+\([^)]*\))?)?',
        r'(?:GE-Proton|Proton-GE)[\s\d.\-]+(?:\([^)]*\))?',
        r'ProtonPlus|ProtonUp-Qt|Protontricks|Winetricks|SteamTinkerLaunch',
        r'Steam Linux Runtime(?:\s+.*)?',
        r'Steam Runtime(?:\s+\d+(?:\.\d+)*(?:\s+\([^)]*\))?)?',
        r'Steamworks (?:Common Redistributables|Shared)',
        r'Steam (?:Common Redistributables|Redistributables)',
    )
    return any(re.fullmatch(pattern, name, re.I) for pattern in patterns) or (Path(root)/'compatibilitytool.vdf').is_file()


def match_mod(game, items):
    items = [i for i in items if i.get('modFileUrl') and i.get('type', 'ready') == 'ready']
    by_id = [i for i in items if i.get('appid') == game['appid']]
    if len(by_id) == 1:
        return by_id[0]
    keys = {game_key(game['name'])}
    if game.get('path'):
        keys.add(game_key(Path(game['path']).name))
    keys.discard('')
    matches = [i for i in items if keys.intersection((game_key(i['title']), game_key(i['slug'])))]
    return matches[0] if len(matches) == 1 else None


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    os.replace(tmp, path)


def digest(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def inside(root, rel, allow_leaf_link=False):
    p = PurePosixPath(rel.replace('\\', '/'))
    if not p.parts or p.is_absolute() or '..' in p.parts or ':' in str(p):
        raise ValueError('안전하지 않은 파일 경로: ' + rel)
    root = Path(root).resolve()
    result = root.joinpath(*p.parts)
    current = root
    for index, part in enumerate(p.parts):
        current = current / part
        if current.is_symlink() and not (allow_leaf_link and index == len(p.parts)-1):
            raise ValueError('심볼릭 링크 경로는 지원하지 않습니다: ' + rel)
    check = result.parent.resolve() if allow_leaf_link else result.resolve()
    if not check.is_relative_to(root):
        raise ValueError('게임 폴더를 벗어나는 경로입니다.')
    return result


def parse_catalog(page):
    """Read Next.js server-rendered props, without executing site JavaScript."""
    chunks = []
    for payload in re.findall(r'self\.__next_f\.push\((.*?)\)</script>', page, re.S):
        try:
            v = json.loads(payload)
            if len(v) > 1 and isinstance(v[1], str):
                chunks.append(v[1])
        except (ValueError, TypeError):
            continue
    decoder = json.JSONDecoder()
    items = {}
    for chunk in chunks:
        for match in re.finditer(r'\{"id":', chunk):
            try:
                obj, _ = decoder.raw_decode(chunk[match.start():])
                if obj.get('slug') and 'modFileUrl' in obj and obj.get('status') == 'published':
                    items[obj['slug']] = {k: obj.get(k) for k in (
                        'slug', 'title', 'type', 'gameVersionEn', 'modFileUrl',
                        'modFileName', 'modFileSize', 'updatedAt')}
            except (ValueError, TypeError):
                continue
    if not items:
        raise ValueError('사이트의 목록 형식이 바뀌었거나 목록이 비어 있습니다.')
    return sorted(items.values(), key=lambda x: x['title'].lower())


class TrustedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, urllib.parse.urlsplit(req.full_url).hostname)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_url(url, host):
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or p.hostname != host or p.username or p.password or p.port not in (None, 443):
        raise ValueError('허용되지 않은 다운로드 주소입니다.')


def open_url(url, host, headers=None):
    validate_url(url, host)
    return urllib.request.build_opener(TrustedRedirect(), urllib.request.HTTPSHandler(context=https_context())).open(
        urllib.request.Request(url, headers={'User-Agent': 'Decky-Eclipse/0.2', **(headers or {})}), timeout=45)


class EclipseManager:
    def __init__(self, plugin, settings, runtime, home):
        self.plugin, self.settings, self.runtime, self.home = map(Path, (plugin, settings, runtime, home))
        self.settings.mkdir(parents=True, exist_ok=True)
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.progress = {'phase': 'idle', 'message': '대기 중', 'percent': 0, 'appid': None}
        self.recipes = json.loads((self.plugin / 'recipes.json').read_text(encoding='utf8'))

    def status(self):
        return dict(self.progress)

    def update(self, phase, message, percent=None, appid=None):
        self.progress = dict(phase=phase, message=message,
                             percent=max(0, min(100, percent if percent is not None else self.progress['percent'])),
                             appid=appid if appid is not None else self.progress.get('appid'))

    def copy_progress(self, source, target, phase, message, start, end, completed, total):
        """Report byte progress, including during a single large executable copy."""
        with open(source, 'rb') as src, open(target, 'wb') as dst:
            while chunk := src.read(1024 * 1024):
                dst.write(chunk)
                completed += len(chunk)
                self.update(phase, message, start + (end - start) * completed / max(total, 1))
        shutil.copystat(source, target)
        return completed

    def catalog(self, refresh=False):
        cache = self.settings / 'catalog.json'
        error = None
        if refresh:
            try:
                with open_url(SOURCE, 'www.steamdeckbase.org') as r:
                    raw = r.read(8 * 1024**2 + 1)
                    if len(raw) > 8 * 1024**2:
                        raise ValueError('목록 응답이 너무 큽니다.')
                    save(cache, parse_catalog(raw.decode('utf8')))
            except Exception as exc:
                error = str(exc)
        path = cache if cache.exists() else self.plugin / 'catalog.json'
        items = json.loads(path.read_text(encoding='utf8'))
        for item in items:
            recipe = self.recipes.get(item['slug'])
            item['supported'] = bool(recipe and recipe['url'] == item['modFileUrl'] and item.get('type', 'ready') == 'ready')
            item['appid'] = recipe['appid'] if recipe else None
            item['page'] = SOURCE + '/' + item['slug']
        return {'items': items, 'error': error, 'cached': not refresh or bool(error)}

    def games(self):
        from steamdata import shortcuts
        steam = self.home / '.local/share/Steam'
        if not steam.exists():
            steam = self.home / '.steam/steam'
        libraries = {steam}
        vdf = steam / 'steamapps/libraryfolders.vdf'
        if vdf.exists():
            for p in re.findall(r'"path"\s*"([^"\n]+)"', vdf.read_text(encoding='utf8')):
                libraries.add(Path(p.replace('\\\\', '\\')))
        games = []
        for lib in libraries:
            for manifest in (lib / 'steamapps').glob('appmanifest_*.acf'):
                data = dict(re.findall(r'"([^"\n]+)"\s*"([^"\n]*)"', manifest.read_text(encoding='utf8')))
                if not all(data.get(k) for k in ('appid', 'installdir', 'name', 'buildid')):
                    continue
                root = inside(lib / 'steamapps/common', data['installdir'])
                if is_steam_tool(data['name'], root):
                    continue
                if root.is_dir():
                    state = self.journal(data['appid'])
                    games.append(dict(appid=data['appid'], name=data['name'], build=data['buildid'],
                                      path=str(root), installed=state.exists(), source='steam'))
        games.extend(g for g in shortcuts(self.home) if g['appid'] not in {x['appid'] for x in games}
                     and not is_steam_tool(g['name'], g['path']))
        items = self.catalog()['items']
        for game in games:
            mod = match_mod(game, items)
            recipe = self.recipes.get(mod['slug']) if mod else None
            if game.get('source') == 'shortcut' and recipe:
                anchors = recipe.get('anchors', []) + recipe.get('anchor_dirs', [])
                if anchors:
                    candidate = Path(game['path'])
                    for possible in [candidate, *list(candidate.parents)[:4]]:
                        if possible == possible.parent or possible == self.home:
                            continue
                        if all(inside(possible, a).exists() for a in anchors):
                            game['path'] = str(possible)
                            break
            build_mismatch = bool(mod and recipe and recipe.get('builds') and game.get('source')!='shortcut'
                                  and game['build'] not in recipe['builds'])
            can_install = bool(mod and mod['supported'] and recipe)
            if not mod:
                reason = '배포 목록에서 이 게임의 ECLIPSE 모드를 찾지 못했습니다.'
            elif not mod['supported']:
                reason = '배포 파일이 변경되었습니다. 플러그인을 업데이트하세요.'
            elif build_mismatch:
                reason = '설치된 빌드와 지원 빌드가 다릅니다. 지원 빌드: ' + ', '.join(recipe['builds'])
            else:
                reason = '자동 다운로드 및 설치를 지원합니다.'
            state_path = self.journal(game['appid'])
            state = json.loads(state_path.read_text(encoding='utf8')) if state_path.exists() else {}
            game.update(installed=state_path.exists(), launch_required=bool(recipe and recipe.get('launch')),
                        launch_pending=state.get('phase') in ('install_launch_pending', 'restore_launch_pending'),
                        notes=recipe.get('notes',[]) if recipe else [],
                        download_size=sum(a.get('size',0) for a in ([recipe]+recipe.get('extras',[]))) if recipe else 0,
                        mod_available=bool(mod), build_mismatch=build_mismatch, mod_slug=mod['slug'] if mod else None,
                        mod_title=mod['title'] if mod else None,
                        mod_version=recipe.get('version',mod.get('gameVersionEn')) if recipe and mod else mod.get('gameVersionEn') if mod else None,
                        can_install=can_install, support_reason=reason)
        return sorted(games, key=lambda g: (not g['mod_available'], g['name'].lower()))

    def journal(self, appid):
        if not str(appid).isdigit():
            raise ValueError('잘못된 Steam AppID입니다.')
        return self.settings / 'backups' / str(appid) / 'journal.json'

    def game(self, appid):
        return next((g for g in self.games() if g['appid'] == str(appid)), None)

    def stopped(self, appid, root):
        # Refuse writes while Steam reports the app running or Wine is executing its files.
        proc = Path('/proc')
        if not proc.exists():
            return
        for pid in proc.iterdir():
            if not pid.name.isdigit():
                continue
            try:
                env = (pid / 'environ').read_bytes().split(b'\0')
                if any(x in env for x in (f'SteamAppId={appid}'.encode(), f'SteamGameId={appid}'.encode())):
                    raise ValueError('게임을 완전히 종료한 뒤 다시 시도하세요.')
                cmd = (pid / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
                if str(root) in cmd and '.exe' in cmd.lower():
                    raise ValueError('게임을 완전히 종료한 뒤 다시 시도하세요.')
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                pass

    def download(self, recipe, target):
        start, end = getattr(self, 'download_window', (2, 65))
        self.update('download', '다운로드 중', start)
        expected = recipe.get('size', 0)
        if expected > LIMIT:
            raise ValueError('다운로드 크기 제한을 초과했습니다.')
        def report(total):
            value = min(end, start + total * (end-start)/expected) if expected else start
            self.update('download', f'다운로드 중 · {total // 1024**2} MB', max(self.progress['percent'],value))
        with open(target,'w+b') as f:
            offset = 0
            while not expected or offset < expected:
                # Bound retry costs for multi-GB releases instead of restarting an entire download.
                last = min(expected-1,offset+64*1024**2-1) if expected else None
                for attempt in range(3):
                    try:
                        headers = {'Range':f'bytes={offset}-{last}'} if last is not None else {}
                        with open_url(recipe['url'],FILE_HOST,headers) as r:
                            partial = r.status == 206
                            if partial and (not expected or r.headers.get('Content-Range') != f'bytes {offset}-{last}/{expected}'):
                                raise ValueError('다운로드 구간 또는 배포 파일 크기가 변경되었습니다.')
                            if not partial and offset:
                                raise ValueError('서버가 다운로드 이어받기를 지원하지 않습니다.')
                            length = last-offset+1 if partial else int(r.headers.get('Content-Length',0))
                            if not partial and expected and length and length != expected:
                                raise ValueError('배포 파일 크기가 검증된 정보와 다릅니다.')
                            f.seek(offset);f.truncate(offset);received=0
                            while block := r.read(1024*1024):
                                received += len(block)
                                if offset+received>LIMIT or (length and received>length):
                                    raise ValueError('다운로드 크기 제한을 초과했습니다.')
                                f.write(block);report(offset+received)
                            if (length and received!=length) or (not partial and expected and received!=expected):
                                raise ValueError('다운로드가 완전하지 않습니다.')
                            offset += received
                            if not partial:
                                expected=offset
                            break
                    except Exception:
                        if attempt == 2:
                            raise
                        self.update('download',f'다운로드 재시도 중 · {attempt+1}/2')
                if not expected or not offset:
                    raise ValueError('다운로드 파일이 비어 있습니다.')
        self.update('verify', '다운로드 파일 검사 중', end)
        if digest(target) != recipe['sha256']:
            raise ValueError('배포 파일이 변경되었습니다. 설치 규칙 업데이트가 필요합니다.')

    def extract(self, archive, dest):
        self.update('extract', '압축 해제 중', getattr(self,'extract_percent',68))
        tool = self.extractor()
        if not tool:
            raise ValueError('RAR 압축 해제용 7zz 또는 7z가 필요합니다. README의 설치 안내를 확인하세요.')
        # Exact archive hash is pinned in a local recipe before invoking the extractor.
        include = dest.parent / ('include-' + dest.name + '.txt')
        include.write_text('\n'.join(getattr(self, 'extraction_files', [])), encoding='utf8')
        subprocess.run([tool, 'x', '-y', '-bd', '-spd', '-i@'+str(include), '-o' + str(dest), str(archive)],
                       check=True, capture_output=True, timeout=3600)
        total = 0
        for f in dest.rglob('*'):
            if f.is_symlink():
                raise ValueError('압축 파일에 심볼릭 링크가 있습니다.')
            if f.is_file():
                total += f.stat().st_size
        if total > 4 * LIMIT:
            raise ValueError('압축 해제 크기 제한을 초과했습니다.')

    def extractor(self):
        bundled = self.plugin / 'bin/7zzs'
        if sys_platform_linux() and bundled.is_file():
            if not os.access(bundled, os.X_OK):
                bundled.chmod(0o755)
            return str(bundled)
        return shutil.which('7zz') or shutil.which('7z')

    def apply(self, slug, appid, launch_before=None, allow_build_mismatch=False):
        if not self.lock.acquire(blocking=False):
            return {'ok': False, 'error': '다른 작업이 진행 중입니다.'}
        try:
            from operations import apply
            return apply(self, slug, str(appid), launch_before, allow_build_mismatch)
        finally:
            self.lock.release()

    def _restore(self, appid):
        from operations import restore
        return restore(self, str(appid))

    def restore(self, appid):
        if not self.lock.acquire(blocking=False):
            return {'ok': False, 'error': '다른 작업이 진행 중입니다.'}
        try:
            return self._restore(str(appid))
        except Exception as exc:
            self.update('error', str(exc))
            return {'ok': False, 'error': str(exc)}
        finally:
            self.lock.release()

    def launch_task(self, appid=None):
        from operations import pending_launch
        return pending_launch(self, appid)

    def finish_launch(self, appid):
        from operations import finish_launch
        with self.lock:
            return finish_launch(self, str(appid))

    def fail_launch(self, message):
        self.update('error', message)
        return {'ok': False, 'error': message}

    def read_launch_options(self, appid):
        from steamdata import launch_options
        return launch_options(self.home, str(appid))


def sys_platform_linux():
    import sys
    return sys.platform == 'linux'
