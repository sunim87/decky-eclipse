import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const dir = path.dirname(fileURLToPath(import.meta.url));
const dom = new JSDOM('<!doctype html><html><body></body></html>', {url: 'http://localhost'});
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, 'navigator', {value: dom.window.navigator, configurable: true});
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
await build({
  entryPoints: [path.join(dir, 'ui.tsx')], bundle: true, format: 'esm', platform: 'node',
  jsx: 'automatic', outfile: path.join(dir, '.bundle.mjs'),
  external: ['react', 'react-dom/client', 'react-icons/fa'],
  alias: {'@decky/ui': path.join(dir, 'mock-ui.tsx'), '@decky/api': path.join(dir, 'mock-api.ts')},
});
await import(pathToFileURL(path.join(dir, '.bundle.mjs')).href);
