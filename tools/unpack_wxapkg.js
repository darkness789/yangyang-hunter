// Read a locally cached PC WeChat V1MMWX package. Format reference:
// https://github.com/BlackTrace/pc_wxapkg_decrypt
// https://github.com/Ccccccccvvm/unpack-wxapkg
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const [,, input, appid, output] = process.argv;
if (!input || !/^wx[0-9a-f]{16}$/i.test(appid || '') || !output) {
  process.stderr.write('Usage: node tools/unpack_wxapkg.js package.wxapkg wx<16hex> output_dir\n');
  process.exit(2);
}

const source = fs.readFileSync(input);
if (source.subarray(0, 6).toString() !== 'V1MMWX') throw new Error('Not a V1MMWX package');
const key = crypto.pbkdf2Sync(appid, 'saltiest', 1000, 32, 'sha1');
const decipher = crypto.createDecipheriv('aes-256-cbc', key, Buffer.from('the iv: 16 bytes'));
decipher.setAutoPadding(false);
const head = Buffer.concat([decipher.update(source.subarray(6, 1030)), decipher.final()]).subarray(0, 1023);
const xorKey = appid.charCodeAt(appid.length - 2);
const tail = Buffer.from(source.subarray(1030));
for (let i = 0; i < tail.length; i++) tail[i] ^= xorKey;
const pack = Buffer.concat([head, tail]);
if (pack[0] !== 0xbe || pack[13] !== 0xed) throw new Error('Decryption failed or unsupported package format');

const indexLength = pack.readUInt32BE(5);
const bodyLength = pack.readUInt32BE(9);
const count = pack.readUInt32BE(14);
if (count > 10000 || indexLength + bodyLength + 14 > pack.length + 16) {
  throw new Error('Invalid package lengths');
}
const root = path.resolve(output);
let pos = 18;
let extracted = 0;
for (let i = 0; i < count; i++) {
  if (pos + 4 > pack.length) throw new Error('Truncated index');
  const length = pack.readUInt32BE(pos); pos += 4;
  if (length > 4096 || pos + length + 8 > pack.length) throw new Error('Invalid file name length');
  const name = pack.subarray(pos, pos + length).toString('utf8'); pos += length;
  const offset = pack.readUInt32BE(pos); pos += 4;
  const size = pack.readUInt32BE(pos); pos += 4;
  if (offset + size > pack.length) throw new Error(`Invalid file range: ${name}`);
  const target = path.resolve(root, name.replace(/^[\\/]+/, ''));
  if (target !== root && !target.startsWith(root + path.sep)) throw new Error(`Unsafe path: ${name}`);
  fs.mkdirSync(path.dirname(target), {recursive: true});
  fs.writeFileSync(target, pack.subarray(offset, offset + size));
  extracted++;
}
process.stdout.write(JSON.stringify({files: extracted, bytes: pack.length, output: root}) + '\n');
