/* Windows adapter: package rendered PNG frames into a multi-resolution ICO.
 * Usage: node scripts/export_windows_icon.cjs SOURCE.svg OUTPUT.ico RENDERER_MODULE
 * RENDERER_MODULE is the installed @resvg/resvg-js directory. No project runtime dependency.
 */
const fs = require('node:fs');
const path = require('node:path');
const [source, output, renderer] = process.argv.slice(2);
if (!source || !output || !renderer) throw new Error('Expected SOURCE.svg OUTPUT.ico RENDERER_MODULE');
const {Resvg} = require(path.resolve(renderer));
const svg = fs.readFileSync(source, 'utf8');
const sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256];
const frames = sizes.map(size => new Resvg(svg, {fitTo: {mode: 'width', value: size}}).render().asPng());
const directory = Buffer.alloc(6 + sizes.length * 16);
directory.writeUInt16LE(1, 2);
directory.writeUInt16LE(sizes.length, 4);
let offset = directory.length;
sizes.forEach((size, i) => {
  const entry = 6 + i * 16;
  directory[entry] = directory[entry + 1] = size === 256 ? 0 : size;
  directory.writeUInt16LE(1, entry + 4);
  directory.writeUInt16LE(32, entry + 6);
  directory.writeUInt32LE(frames[i].length, entry + 8);
  directory.writeUInt32LE(offset, entry + 12);
  offset += frames[i].length;
});
fs.mkdirSync(path.dirname(path.resolve(output)), {recursive: true});
fs.writeFileSync(output, Buffer.concat([directory, ...frames]));
console.log(JSON.stringify({output: path.resolve(output), sizes, format: 'ICO with RGBA PNG frames'}));
