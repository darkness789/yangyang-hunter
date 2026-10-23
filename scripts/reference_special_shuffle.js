// Offline differential check against the functions in the locally cached
// game bundle. Prints JSON only; never opens or clicks the game window.
const fs = require('node:fs');
const vm = require('node:vm');

const [,, bundlePath, mapPath, seedPath] = process.argv;
if (!bundlePath || !mapPath || !seedPath) {
  process.stderr.write('Usage: node reference_special_shuffle.js game.js map.json seed.json\n');
  process.exit(2);
}
const source = fs.readFileSync(bundlePath, 'utf8');
const classStart = source.indexOf('class i{constructor(){this._randTimes=0}');
const classEnd = source.indexOf('}n.XorShift=i', classStart);
const shuffleStart = source.indexOf('static shuffle(e,t,n){');
const shuffleEnd = source.indexOf('static shuffleArrayIndex', shuffleStart);
if (classStart < 0 || classEnd < 0 || shuffleStart < 0 || shuffleEnd < 0)
  throw new Error('The observed client functions were not found');
const XorShift = vm.runInNewContext('(' + source.slice(classStart, classEnd + 1) + ')');
const Util = vm.runInNewContext('(class R {' + source.slice(shuffleStart, shuffleEnd) + '})');
const map = JSON.parse(fs.readFileSync(mapPath, 'utf8'));
const seed = JSON.parse(fs.readFileSync(seedPath, 'utf8')).map_seed;
const rng = new XorShift();
rng.setSeed(seed);
rng.random();
const pool = [];
for (const [type, groups] of Object.entries(map.blockTypeData).sort((a,b) => +a[0]-+b[0]))
  for (let i=0; i<groups*3; i++) pool.push(+type);
Util.shuffle(pool, rng);
const cards = Object.entries(map.levelData).sort((a,b) => +a[0]-+b[0])
  .flatMap(([,items]) => items);
for (const card of cards) if (!card.type) card.type = pool.pop();
const changing = cards.filter(card => card.metaType === 2)
  .sort((a,b) => a.layerNum-b.layerNum || a.rowNum-b.rowNum || a.rolNum-b.rolNum);
function snapshot() {
  return {types: Object.fromEntries(changing.map(card => [card.id, card.type])),
    state: [rng._state0U>>>0,rng._state0L>>>0,rng._state1U>>>0,rng._state1L>>>0],
    draws: rng.randTimes};
}
function recolor() {
  const active = changing.filter(card => !removed.has(card.id));
  if (active.length > 1) {
    const types = Util.shuffle(active.map(card => card.type),rng);
    active.forEach((card,i) => card.type = types[i]);
  }
}
const removed = new Set();
recolor();
const initial = snapshot();
const cycles = [];
for (let cycle=0; cycle<12; cycle++) {
  if (cycle % 3 === 1 && changing[cycle]) removed.add(changing[cycle].id);
  recolor();
  cycles.push(snapshot());
}
process.stdout.write(JSON.stringify({initial, cycles, changingIds: changing.map(c=>c.id),
  ordinaryTypes: Object.fromEntries(cards.filter(c=>c.metaType!==2).map(c=>[c.id,c.type]))}));
