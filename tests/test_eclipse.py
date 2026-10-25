import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import shutil
import struct
import io
import hashlib
import ssl
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('eclipse', Path(__file__).parents[1] / 'eclipse.py')
eclipse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eclipse)


class ManagerTests(unittest.TestCase):
    def test_bundled_ca_loads_when_python_default_store_is_empty(self):
        empty = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.assertEqual(empty.cert_store_stats()['x509_ca'],0)
        eclipse.https_context.cache_clear()
        try:
            with patch.object(eclipse.ssl,'create_default_context',return_value=empty), patch.object(eclipse,'CA_BUNDLES',()):
                context=eclipse.https_context()
            self.assertGreater(context.cert_store_stats()['x509_ca'],100)
            self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
        finally:
            eclipse.https_context.cache_clear()

    def test_steamos_ca_store_is_loaded_explicitly(self):
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        bundle=Path(__file__).parents[1]/'certs/cacert.pem'
        eclipse.https_context.cache_clear()
        try:
            with patch.object(eclipse.ssl,'create_default_context',return_value=context), patch.object(eclipse,'CA_BUNDLES',(str(bundle),)):
                self.assertGreater(eclipse.https_context().cert_store_stats()['x509_ca'],100)
        finally:
            eclipse.https_context.cache_clear()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parents[1])
        self.base = Path(self.temp.name)
        self.plugin = self.base / 'plugin'
        self.plugin.mkdir()
        self.home = self.base / 'home'
        steam = self.home / '.local/share/Steam/steamapps'
        steam.mkdir(parents=True)
        self.root = steam / 'common/Test Game'
        self.root.mkdir(parents=True)
        (self.root / 'game.exe').write_bytes(b'ORIGINAL')
        self.recipe = {'appid': '123', 'builds': ['456'], 'url': 'https://file.steamdeckbase.org/test.rar',
                       'payload': 'Test', 'files': ['game.exe', 'mods/new.pak'], 'anchors': ['game.exe'], 'sha256': 'test'}
        (self.plugin / 'recipes.json').write_text(json.dumps({'test': self.recipe}))
        (self.plugin / 'catalog.json').write_text(json.dumps([{'slug':'test', 'title':'Test', 'modFileUrl': self.recipe['url']}]))
        (steam / 'appmanifest_123.acf').write_text('"appid" "123" "name" "Test" "installdir" "Test Game" "buildid" "456"')
        self.manager = eclipse.EclipseManager(self.plugin, self.base / 'settings', self.base / 'runtime', self.home)
        self.manager.extractor = lambda: 'test-extractor'
        self.manager.download = lambda recipe, target: target.write_bytes(b'archive')
        self.manager.stopped = lambda appid, root: None
        self.manager.extract = self.extract

    def tearDown(self):
        self.temp.cleanup()

    def extract(self, archive, dest):
        payload = dest / 'Test'
        (payload / 'mods').mkdir(parents=True)
        (payload / 'game.exe').write_bytes(b'MODDED')
        (payload / 'mods/new.pak').write_bytes(b'NEW')

    def test_round_trip(self):
        self.assertTrue(self.manager.apply('test', '123')['ok'])
        self.assertEqual((self.root / 'game.exe').read_bytes(), b'MODDED')
        self.assertTrue(self.manager.restore('123')['ok'])
        self.assertEqual((self.root / 'game.exe').read_bytes(), b'ORIGINAL')
        self.assertFalse((self.root / 'mods').exists())

    def test_update_conflict_preserves_files_and_backup(self):
        self.assertTrue(self.manager.apply('test', '123')['ok'])
        (self.root / 'game.exe').write_bytes(b'GAME UPDATE')
        self.assertFalse(self.manager.restore('123')['ok'])
        self.assertTrue(self.manager.journal('123').exists())
        self.assertEqual((self.root / 'game.exe').read_bytes(), b'GAME UPDATE')
        self.assertTrue((self.root / 'mods/new.pak').exists())

    def test_failed_apply_rolls_back(self):
        real_replace = eclipse.os.replace
        def fail(src, dst):
            if str(dst).endswith('new.pak'):
                raise OSError('simulated write failure')
            return real_replace(src, dst)
        with patch.object(eclipse.os, 'replace', side_effect=fail):
            self.assertFalse(self.manager.apply('test', '123')['ok'])
        self.assertEqual((self.root / 'game.exe').read_bytes(), b'ORIGINAL')
        self.assertFalse(self.manager.journal('123').exists())

    def test_build_mismatch_and_wrong_game(self):
        self.manager.recipes['test']['builds'] = ['999']
        self.assertFalse(self.manager.apply('test', '123')['ok'])
        self.assertFalse(self.manager.apply('test', '999')['ok'])
        self.assertFalse(self.manager.journal('123').exists())

    def test_restart_can_restore_interrupted_install(self):
        self.assertTrue(self.manager.apply('test', '123')['ok'])
        path = self.manager.journal('123')
        state = json.loads(path.read_text())
        state['phase'] = 'applying'
        eclipse.save(path, state)
        new = eclipse.EclipseManager(self.plugin, self.base / 'settings', self.base / 'runtime', self.home)
        new.stopped = lambda appid, root: None
        self.assertTrue(new.restore('123')['ok'])
        self.assertEqual((self.root / 'game.exe').read_bytes(), b'ORIGINAL')

    def test_corrupt_backup_prevents_all_restore_writes(self):
        self.assertTrue(self.manager.apply('test', '123')['ok'])
        backup = self.manager.journal('123').parent / 'original/game/game.exe'
        backup.write_bytes(b'CORRUPT')
        self.assertFalse(self.manager.restore('123')['ok'])
        self.assertEqual((self.root / 'game.exe').read_bytes(), b'MODDED')

    def test_unsafe_paths_and_urls(self):
        for rel in ['../outside', '/absolute', 'C:/outside', 'mods/../../outside']:
            with self.assertRaises(ValueError):
                eclipse.inside(self.root, rel)
        for url in ['http://file.steamdeckbase.org/a', 'https://evil.example/a', 'https://file.steamdeckbase.org:444/a']:
            with self.assertRaises(ValueError):
                eclipse.validate_url(url, eclipse.FILE_HOST)

    def test_catalog_parser(self):
        item = dict(id=1, slug='test', title='Test', modFileUrl=self.recipe['url'], status='published')
        page = '<script>self.__next_f.push(' + json.dumps([1, '1:' + json.dumps(item)]) + ')</script>'
        self.assertEqual(eclipse.parse_catalog(page)[0]['slug'], 'test')

    def test_installed_games_support_and_build_status(self):
        game = self.manager.games()[0]
        self.assertTrue(game['mod_available'])
        self.assertTrue(game['can_install'])
        self.assertFalse(game['build_mismatch'])
        self.manager.recipes['test']['builds'] = ['999']
        game = self.manager.games()[0]
        self.assertTrue(game['mod_available'])
        self.assertTrue(game['can_install'])
        self.assertTrue(game['build_mismatch'])
        self.assertIn('지원 빌드: 999', game['support_reason'])
        self.manager.recipes.clear()
        game = self.manager.games()[0]
        self.assertTrue(game['mod_available'])
        self.assertFalse(game['can_install'])
        self.assertIn('업데이트', game['support_reason'])
        self.assertFalse(game['build_mismatch'])

    def test_exact_title_matching_and_id_priority(self):
        items = [{'appid': None, 'title': 'S.T.A.L.K.E.R. 2: Heart of Chornobyl', 'slug': 'stalker2', 'modFileUrl':'https://file.steamdeckbase.org/test.rar'}]
        game = {'appid': '7', 'name': 'STALKER 2: Heart of Chornobyl™'}
        self.assertIs(eclipse.match_mod(game, items), items[0])
        self.assertIsNone(eclipse.match_mod({'appid':'7', 'name':'STALKER'}, items))
        items[0]['appid'] = '7'
        self.assertIs(eclipse.match_mod({'appid':'7', 'name':'한국어 제목'}, items), items[0])
        self.assertIsNone(eclipse.match_mod({'appid':'8', 'name':'Unrelated'}, items))
        items[0]['type'] = 'updates'
        self.assertIsNone(eclipse.match_mod(game, items))

    def test_byte_progress_and_operation_game(self):
        events = []
        update = self.manager.update
        def record(*args, **kwargs):
            update(*args, **kwargs)
            events.append(self.manager.status())
        self.manager.update = record
        self.assertTrue(self.manager.apply('test', '123')['ok'])
        values = [e['percent'] for e in events]
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[-1], 100)
        self.assertTrue(all(e['appid'] == '123' for e in events))
        self.assertTrue(any(e['phase'] == 'apply' and '복사 중' in e['message'] for e in events))
        events.clear()
        self.assertTrue(self.manager.restore('123')['ok'])
        self.assertEqual(events[-1]['percent'], 100)
        self.assertTrue(any(e['phase'] == 'restore' and '원본 복사 중' in e['message'] for e in events))

    def test_removed_originals_are_backed_up_and_restored(self):
        (self.root/'optional-high.pak').write_bytes(b'HIGH TEXTURES')
        self.manager.recipes['test']['remove']=[{'folder':'.','glob':'*optional*'}]
        # Use an actual nonempty path; the engine intentionally rejects '.' as an installation path.
        (self.root/'data').mkdir()
        shutil.move(self.root/'optional-high.pak',self.root/'data/optional-high.pak')
        self.manager.recipes['test']['remove']=[{'folder':'data','glob':'*optional*'}]
        self.assertTrue(self.manager.apply('test','123')['ok'])
        self.assertFalse((self.root/'data/optional-high.pak').exists())
        self.assertTrue(self.manager.restore('123')['ok'])
        self.assertEqual((self.root/'data/optional-high.pak').read_bytes(),b'HIGH TEXTURES')

    def test_extra_archive_and_proton_file_round_trip(self):
        prefix=self.root.parents[1]/'compatdata/123/pfx/drive_c/windows/system32'
        prefix.mkdir(parents=True)
        (prefix/'cryptbase.dll').write_bytes(b'WINE DLL')
        original_extract=self.manager.extract
        def extract(archive,dest):
            if archive.name=='payload-0.rar':
                original_extract(archive,dest)
                (dest/'Test/CryptBase.dll').write_bytes(b'NATIVE DLL')
            else:
                (dest/'Textures').mkdir()
                (dest/'Textures/extra.pak').write_bytes(b'COMPANION')
        self.manager.extract=extract
        recipe=self.manager.recipes['test']
        recipe['files'].append('CryptBase.dll')
        recipe['prefix_copies']=[{'source':'CryptBase.dll','path':'CryptBase.dll'}]
        recipe['extras']=[{'payload':'Textures','files':['extra.pak'],'url':'https://file.steamdeckbase.org/extra.rar','size':10}]
        result=self.manager.apply('test','123')
        self.assertTrue(result['ok'],result)
        self.assertEqual((prefix/'cryptbase.dll').read_bytes(),b'NATIVE DLL')
        self.assertEqual([p.name for p in prefix.iterdir()],['cryptbase.dll'])
        self.assertEqual((self.root/'extra.pak').read_bytes(),b'COMPANION')
        self.assertTrue(self.manager.restore('123')['ok'])
        self.assertEqual((prefix/'cryptbase.dll').read_bytes(),b'WINE DLL')
        self.assertFalse((self.root/'extra.pak').exists())

    def test_start_options_journal_survives_until_ack(self):
        self.manager.recipes['test']['launch']={'env':{'SteamDeck':'0'},'args':'-example=1'}
        self.assertFalse(self.manager.apply('test','123')['ok'])
        self.assertFalse(self.manager.journal('123').exists())
        result=self.manager.apply('test','123','OLD=1 %command% -user=2')
        self.assertTrue(result['ok'],result)
        self.assertTrue(result['launch_pending'])
        task=self.manager.launch_task('123')
        self.assertIn('SteamDeck="0"',task['options'])
        self.assertIn('OLD=1',task['options'])
        self.assertIn('-user=2',task['options'])
        self.assertIn('-example=1',task['options'])
        self.assertEqual(self.manager.status()['percent'],99)
        self.manager.finish_launch('123')
        self.assertEqual(self.manager.status()['percent'],100)
        result=self.manager.restore('123')
        self.assertTrue(result['launch_pending'])
        self.assertEqual(self.manager.launch_task('123')['options'],'OLD=1 %command% -user=2')
        self.assertTrue(self.manager.journal('123').exists())
        self.manager.finish_launch('123')
        self.assertFalse(self.manager.journal('123').exists())

    def test_launch_override_preserves_other_dlls(self):
        from operations import merge_launch
        value=merge_launch('WINEDLLOVERRIDES="dxgi=n,b;version=b" OLD=1 %command%',{'env':{'WINEDLLOVERRIDES':'CryptBase,version=n,b'}})
        self.assertIn('dxgi=n,b;CryptBase,version=n,b',value)
        self.assertNotIn('version=b',value)
        self.assertIn('OLD=1',value)

    def test_version_only_recipe_is_installable(self):
        self.manager.recipes['test']['builds']=[]
        self.assertTrue(self.manager.games()[0]['can_install'])
        self.assertTrue(self.manager.apply('test','123')['ok'])

    def test_mismatched_build_requires_explicit_yes_and_can_restore(self):
        self.manager.recipes['test']['builds']=['999']
        self.assertTrue(self.manager.games()[0]['can_install'])
        self.assertFalse(self.manager.apply('test','123')['ok'])
        self.assertFalse(self.manager.journal('123').exists())
        self.assertFalse(self.manager.apply('test','123',None,'true')['ok'])
        result=self.manager.apply('test','123',None,True)
        self.assertTrue(result['ok'],result)
        state=json.loads(self.manager.journal('123').read_text(encoding='utf8'))
        self.assertTrue(state['build_mismatch_confirmed'])
        self.assertEqual((self.root/'game.exe').read_bytes(),b'MODDED')
        self.assertTrue(self.manager.restore('123')['ok'])
        self.assertEqual((self.root/'game.exe').read_bytes(),b'ORIGINAL')

    def test_legacy_011_backup_can_be_restored(self):
        self.assertTrue(self.manager.apply('test','123')['ok'])
        journal=self.manager.journal('123')
        state=json.loads(journal.read_text(encoding='utf8'))
        state.pop('format');state.pop('roots')
        state['created_dirs']=[d['path'] for d in state['created_dirs']]
        for e in state['entries']:
            e.pop('scope');e.pop('action');e.pop('original_link')
        shutil.move(journal.parent/'original/game/game.exe',journal.parent/'original/game.exe')
        eclipse.save(journal,state)
        self.assertTrue(self.manager.restore('123')['ok'])
        self.assertEqual((self.root/'game.exe').read_bytes(),b'ORIGINAL')

    def test_nonsteam_shortcut_and_localconfig_reading(self):
        from steamdata import shortcuts,launch_options
        config=self.home/'.local/share/Steam/userdata/1/config';config.mkdir(parents=True)
        def string(key,value):
            return b'\x01'+key.encode()+b'\0'+value.encode()+b'\0'
        data=b'\x00shortcuts\0\x000\0'+b'\x02appid\0'+struct.pack('<I',4000000000)
        data+=string('AppName','Test')+string('Exe','"'+str(self.root/'game.exe')+'"')
        data+=string('StartDir','"'+str(self.root)+'"')+string('LaunchOptions','ENV=1 %command%')+b'\x08\x08'
        (config/'shortcuts.vdf').write_bytes(data)
        found=shortcuts(self.home)
        self.assertEqual(found[0]['appid'],'4000000000')
        self.assertEqual(found[0]['path'],str(self.root.resolve()))
        self.assertEqual(launch_options(self.home,'4000000000'),'ENV=1 %command%')
        (config/'localconfig.vdf').write_text('"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { "123" { "LaunchOptions" "TEST=1 %command%" } } } } } }',encoding='utf8')
        self.assertEqual(launch_options(self.home,'123'),'TEST=1 %command%')

    def test_range_download_retries_truncated_chunk(self):
        content=b'mod archive bytes'*100
        class Response(io.BytesIO):
            status=206
            headers={'Content-Range':f'bytes 0-{len(content)-1}/{len(content)}'}
        recipe={'url':'https://file.steamdeckbase.org/test.rar','size':len(content),
                'sha256':hashlib.sha256(content).hexdigest()}
        self.manager.download= eclipse.EclipseManager.download.__get__(self.manager)
        with patch.object(eclipse,'open_url',side_effect=[Response(content[:10]),Response(content)]) as request:
            target=self.base/'download.rar'
            self.manager.download(recipe,target)
            self.assertEqual(target.read_bytes(),content)
            self.assertEqual(request.call_count,2)
            self.assertEqual(request.call_args.args[2],{'Range':f'bytes=0-{len(content)-1}'})

    def test_changed_archive_hash_is_rejected(self):
        content=b'changed archive'
        class Response(io.BytesIO):
            status=200
            headers={'Content-Length':str(len(content))}
        recipe={'url':'https://file.steamdeckbase.org/test.rar','size':len(content),'sha256':'0'*64}
        self.manager.download=eclipse.EclipseManager.download.__get__(self.manager)
        with patch.object(eclipse,'open_url',return_value=Response(content)):
            with self.assertRaisesRegex(ValueError,'변경'):
                self.manager.download(recipe,self.base/'download.rar')

    def test_installed_list_excludes_steam_compatibility_tools(self):
        tools=['Proton 10.0','Proton 9.0','Proton Experimental','Proton Hotfix',
               'Proton EasyAntiCheat Runtime','Proton BattlEye Runtime',
               'Steam Linux Runtime 3.0 (sniper)','Steam Linux Runtime 4.0 (medic)',
               'Steamworks Common Redistributables','GE-Proton10-25','ProtonPlus']
        steam=self.root.parents[1]
        for n,name in enumerate(tools,1000):
            directory='tool-'+str(n)
            (steam/'common'/directory).mkdir()
            (steam/f'appmanifest_{n}.acf').write_text(f'"appid" "{n}" "name" "{name}" "installdir" "{directory}" "buildid" "1"')
        self.assertEqual([g['name'] for g in self.manager.games()],['Test'])
        self.assertFalse(eclipse.is_steam_tool('Proton Pulse',self.root))
        self.assertFalse(eclipse.is_steam_tool('Half-Life',self.root))
        (self.root/'compatibilitytool.vdf').write_text('compatibility tool')
        self.assertTrue(eclipse.is_steam_tool('Custom Compatibility Tool',self.root))


if __name__ == '__main__':
    unittest.main()
