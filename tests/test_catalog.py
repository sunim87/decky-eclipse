import json
from pathlib import Path
import re
import unittest


class CatalogCoverageTests(unittest.TestCase):
    def test_all_58_releases_have_pinned_installation_recipes(self):
        root=Path(__file__).parents[1]
        catalog=json.loads((root/'catalog.json').read_text(encoding='utf8'))
        recipes=json.loads((root/'recipes.json').read_text(encoding='utf8'))
        self.assertEqual(len(catalog),58)
        self.assertEqual({i['slug'] for i in catalog},set(recipes))
        appids=[]
        for item in catalog:
            recipe=recipes[item['slug']]
            self.assertEqual(recipe['url'],item['modFileUrl'])
            self.assertTrue(recipe['files'])
            self.assertEqual(len(recipe['files']),len(set(recipe['files'])))
            if recipe['appid']:
                appids.append(recipe['appid'])
            for asset in [recipe]+recipe.get('extras',[]):
                self.assertRegex(asset['sha256'],r'^[a-f0-9]{64}$')
                self.assertGreater(asset['size'],0)
                self.assertGreater(asset['unpacked_size'],0)
                self.assertTrue(asset['url'].startswith('https://file.steamdeckbase.org/'))
                for rel in asset['files']:
                    self.assertFalse(rel.startswith('/') or '..' in Path(rel).parts)
        self.assertEqual(len(appids),57)
        self.assertEqual(len(set(appids)),57)
        self.assertIn('extras',recipes['starfield'])
        self.assertGreater(recipes['starfield']['extras'][0]['size'],8_000_000_000)
        self.assertIn('prefix_copies',recipes['need-for-speed-heat'])
        self.assertIn('launch',recipes['death-stranding-2-on-the-beach'])
        self.assertIn('remove',recipes['hogwarts-legacy'])
