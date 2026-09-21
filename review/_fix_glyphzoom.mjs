import { chromium } from '@playwright/test';
const tag=process.argv[2];
const b=await chromium.launch();
for(const scheme of ['light','dark']){
  const ctx=await b.newContext({viewport:{width:1600,height:1000},colorScheme:scheme,deviceScaleFactor:4});
  const p=await ctx.newPage();
  await p.goto('http://localhost:4180/?s=findings&f=F001&d=core1&v=1&snap=9cc348bd58bb',{waitUntil:'load'});
  await p.waitForTimeout(1800);
  const r=await p.evaluate(()=>{const h=document.querySelector('[role="columnheader"][data-col="id"]');const b=h.getBoundingClientRect();
    return {x:b.x-2,y:b.y-2,width:150,height:b.height+4};});
  await p.screenshot({path:`review/_fixshots/${tag}-glyph-${scheme}.png`,clip:r});
  await ctx.close();
}
await b.close();console.log('ok');
