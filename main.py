"""Decky entry point. All blocking I/O runs outside the RPC event loop."""
import asyncio
import os
import sys
import decky

sys.path.insert(0, os.path.dirname(__file__))
from eclipse import EclipseManager


class Plugin:
    async def _main(self):
        self.manager = EclipseManager(os.path.dirname(__file__), decky.DECKY_PLUGIN_SETTINGS_DIR,
                                      decky.DECKY_PLUGIN_RUNTIME_DIR, decky.HOME)

    async def _unload(self):
        pass

    async def catalog(self, refresh=False):
        return await asyncio.to_thread(self.manager.catalog, refresh)

    async def games(self):
        return await asyncio.to_thread(self.manager.games)

    async def status(self):
        return self.manager.status()

    async def apply(self, slug, appid, launch_before=None, allow_build_mismatch=False):
        return await asyncio.to_thread(self.manager.apply, slug, appid, launch_before, allow_build_mismatch)

    async def restore(self, appid):
        return await asyncio.to_thread(self.manager.restore, appid)

    async def launch_task(self, appid=None):
        return await asyncio.to_thread(self.manager.launch_task, appid)

    async def finish_launch(self, appid):
        return await asyncio.to_thread(self.manager.finish_launch, appid)

    async def fail_launch(self, message):
        return self.manager.fail_launch(message)

    async def read_launch_options(self, appid):
        return await asyncio.to_thread(self.manager.read_launch_options, appid)
