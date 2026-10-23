// Reproduce the game's XorShift shuffle and pop assignment from its cached
// script-bundle (version 501). Input seed must come from a decoded game start.
const fs = require('node:fs');

const [,, mapPath, seedPath, outputPath] = process.argv;
if (!mapPath || !seedPath || !outputPath) {
  process.stderr.write('Usage: node scripts/restore_types.js map.json recovered_seed.json typed_map.json\n');
  process.exit(2);
}
const map = JSON.parse(fs.readFileSync(mapPath, 'utf8'));
const saved = JSON.parse(fs.readFileSync(seedPath, 'utf8'));
if (map.sourceMapMd5 && Array.isArray(saved.map_md5) &&
    !saved.map_md5.includes(map.sourceMapMd5)) {
  throw new Error('The map file belongs to a different game start');
}
const seed = saved.map_seed;
if (!Array.isArray(seed) || seed.length !== 4 || seed.some(x => !Number.isInteger(x))) {
  throw new Error('Expected four integer seed values');
}

class XorShift {
  constructor(values) {
    this.state0U = values[0] | 0;
    this.state0L = values[1] | 0;
    this.state1U = values[2] | 0;
    this.state1L = values[3] | 0;
  }
  random() {
    let e = this.state0U, t = this.state0L, n = this.state1U, i = this.state1L;
    const sum = (i >>> 0) + (t >>> 0);
    const high = (n + e + (sum / 2 >>> 31)) >>> 0;
    const low = sum >>> 0;
    this.state0U = n;
    this.state0L = i;
    let r = 0, c = 0;
    r = (e ^= r = e << 23 | (-512 & t) >>> 9) ^ n;
    c = (t ^= c = t << 23) ^ i;
    r ^= e >>> 18;
    c ^= t >>> 18 | (262143 & e) << 14;
    r ^= n >>> 5;
    c ^= i >>> 5 | (31 & n) << 27;
    this.state1U = r;
    this.state1L = c;
    return 2.3283064365386963e-10 * high + 2220446049250313e-31 * (low >>> 12);
  }
}

const rng = new XorShift(seed);
rng.random(); // resetMapSeed consumes one value before the map shuffle.
const types = [];
for (const [key, groups] of Object.entries(map.blockTypeData).sort((a, b) => +a[0] - +b[0])) {
  for (let i = 0; i < groups * 3; i++) types.push(+key);
}
for (let i = types.length - 1; i >= 0; i--) {
  const j = Math.floor(rng.random() * (i + 1));
  [types[i], types[j]] = [types[j], types[i]];
}
let assigned = 0;
for (const [layer, cards] of Object.entries(map.levelData).sort((a, b) => +a[0] - +b[0])) {
  for (const card of cards) {
    if (card.type === 0) {
      card.type = types.pop();
      assigned++;
    }
  }
}
if (types.length || Object.values(map.levelData).flat().some(card => !card.type)) {
  throw new Error('Map/type counts do not align');
}
// The client shuffles ColorChangedWhenCrush cards once when level two opens.
// Its board iterator visits numeric layer, row, then column keys in order.
const changing = Object.values(map.levelData).flat()
  .filter(card => card.metaType === 2)
  .sort((a, b) => a.layerNum - b.layerNum || a.rowNum - b.rowNum ||
    a.rolNum - b.rolNum);
if (changing.length > 1) {
  const current = changing.map(card => card.type);
  for (let i = current.length - 1; i >= 0; i--) {
    const j = Math.floor(rng.random() * (i + 1));
    [current[i], current[j]] = [current[j], current[i]];
  }
  changing.forEach((card, index) => { card.type = current[index]; });
}
map.specialRng = {
  state: [rng.state0U >>> 0, rng.state0L >>> 0,
          rng.state1U >>> 0, rng.state1L >>> 0],
  changingIds: changing.map(card => card.id),
};
fs.writeFileSync(outputPath, JSON.stringify(map, null, 2));
process.stdout.write(JSON.stringify({levelKey: map.levelKey, assigned,
  changing: changing.length, output: outputPath}) + '\n');
