// Predict the classic client's first shuffle from the captured map seed.
// Usage: node tools/preview_shuffle.js template.json seed.json output.json
const fs = require('node:fs');
const [,, mapPath, seedPath, outputPath] = process.argv;
if (!mapPath || !seedPath || !outputPath) {
  throw new Error('Expected template, seed and output paths');
}
const map = JSON.parse(fs.readFileSync(mapPath, 'utf8'));
const saved = JSON.parse(fs.readFileSync(seedPath, 'utf8'));
if (!saved.map_md5.includes(map.sourceMapMd5)) throw new Error('Map/seed mismatch');
class XorShift {
  constructor(v) {
    this.state0U=v[0]|0; this.state0L=v[1]|0;
    this.state1U=v[2]|0; this.state1L=v[3]|0;
  }
  random() {
    let e=this.state0U,t=this.state0L,n=this.state1U,i=this.state1L;
    const sum=(i>>>0)+(t>>>0), high=(n+e+(sum/2>>>31))>>>0, low=sum>>>0;
    this.state0U=n; this.state0L=i;
    let r=0,c=0;
    r=(e^=r=e<<23|(-512&t)>>>9)^n;
    c=(t^=c=t<<23)^i;
    r^=e>>>18; c^=t>>>18|(262143&e)<<14;
    r^=n>>>5; c^=i>>>5|(31&n)<<27;
    this.state1U=r; this.state1L=c;
    return 2.3283064365386963e-10*high+2220446049250313e-31*(low>>>12);
  }
}
function shuffle(items,rng) {
  for(let i=items.length-1;i>=0;i--) {
    const j=Math.floor(rng.random()*(i+1));
    [items[i],items[j]]=[items[j],items[i]];
  }
  return items;
}
const rng = new XorShift(saved.map_seed);
rng.random();
const groups = [];
for (const [kind,count] of Object.entries(map.blockTypeData).sort((a,b)=>+a[0]-+b[0])) {
  for(let k=0;k<count*3;k++) groups.push(+kind);
}
shuffle(groups,rng);
const layers = Object.entries(map.levelData).sort((a,b)=>+a[0]-+b[0]);
for(const [,cards] of layers) for(const card of cards) {
  if(card.type===0) card.type=groups.pop();
}
const ordered = layers.flatMap(([,cards])=>cards).sort((a,b)=>
  a.layerNum-b.layerNum || a.rowNum-b.rowNum || a.rolNum-b.rolNum);
const availableTypes = shuffle(ordered.map(card=>card.type),rng);
for(const card of ordered) card.type=availableTypes.pop();
map.previewFirstShuffle=true;
fs.writeFileSync(outputPath,JSON.stringify(map,null,2));
process.stdout.write(JSON.stringify({tiles:ordered.length,output:outputPath})+'\n');
