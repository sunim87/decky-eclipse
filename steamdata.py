"""Read Steam configuration and shortcuts. Steam owns all configuration writes."""
from pathlib import Path
import re
import struct
import zlib


def text_vdf(text):
    tokens = re.finditer(r'"((?:[^"\\]|\\.)*)"|([{}])|//[^\n]*', text)
    root = {}; stack = [root]; key = None
    for token in tokens:
        value, brace = token.groups()
        if value is not None:
            value = value.replace('\\"', '"').replace('\\\\', '\\')
            if key is None:
                key = value.lower()
            else:
                stack[-1][key] = value; key = None
        elif brace == '{':
            child = {}; stack[-1][key or ''] = child; stack.append(child); key = None
        elif brace == '}' and len(stack) > 1:
            stack.pop(); key = None
    return root


def binary_vdf(data):
    pos = 0
    def string():
        nonlocal pos
        end = data.index(0, pos)
        value = data[pos:end].decode('utf8', errors='replace'); pos = end + 1
        return value
    def object_value(depth=0):
        nonlocal pos
        if depth > 32:
            raise ValueError('Shortcut nesting limit')
        result = {}
        while pos < len(data):
            kind = data[pos]; pos += 1
            if kind == 8:
                return result
            key = string().lower()
            if kind == 0:
                value = object_value(depth+1)
            elif kind == 1:
                value = string()
            elif kind in (2, 3, 4, 6):
                value = struct.unpack_from('<I', data, pos)[0]; pos += 4
            elif kind == 7:
                value = struct.unpack_from('<Q', data, pos)[0]; pos += 8
            else:
                raise ValueError('Unsupported shortcut field')
            result[key] = value
        if depth==0:
            return result
        raise ValueError('Truncated shortcuts')
    return object_value()


def steam_root(home):
    for rel in ('.local/share/Steam', '.steam/steam', '.steam/root'):
        root = Path(home)/rel
        if (root/'steamapps').is_dir():
            return root.resolve()
    return Path(home)/'.local/share/Steam'


def config_files(home, name):
    return sorted((steam_root(home)/'userdata').glob('*/config/'+name),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def shortcuts(home):
    found = {}
    for file in config_files(home, 'shortcuts.vdf'):
        try:
            values = binary_vdf(file.read_bytes()).get('shortcuts', {})
            for item in values.values():
                if not isinstance(item, dict):
                    continue
                name = item.get('appname', ''); exe = item.get('exe', '').strip()
                start = item.get('startdir', '').strip('" ')
                match = re.match(r'"([^"\n]+)"|([^\s]+)', exe)
                executable = (match.group(1) or match.group(2)) if match else ''
                # Prefer the game executable's actual parent to launcher working directories.
                root = Path(executable).parent if executable.lower().endswith('.exe') else Path(start)
                if not name or not root.is_absolute() or not root.is_dir():
                    continue
                appid = str(item.get('appid') or (zlib.crc32((exe+name).encode()) | 0x80000000))
                if appid not in found:
                    found[appid] = dict(appid=appid, name=name, path=str(root.resolve()), build='',
                                        source='shortcut', shortcut_launch=item.get('launchoptions',''))
        except (OSError, ValueError, KeyError, struct.error):
            continue
    return list(found.values())


def launch_options(home, appid):
    # Reading the newest account's record is a fallback for Steam clients without a getter.
    for file in config_files(home, 'localconfig.vdf'):
        try:
            node = text_vdf(file.read_text(encoding='utf8'))
            for key in ('userlocalconfigstore','software','valve','steam','apps'):
                node = node.get(key, {})
            if str(appid) in node:
                return node[str(appid)].get('launchoptions', '')
        except (OSError, AttributeError, UnicodeError):
            continue
    for game in shortcuts(home):
        if game['appid'] == str(appid):
            return game['shortcut_launch']
    # An existing localconfig with no app entry represents no configured options.
    return '' if config_files(home, 'localconfig.vdf') else None
