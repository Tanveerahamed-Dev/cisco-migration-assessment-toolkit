import { chromium } from '@playwright/test';
const APP='http://localhost:4180';
const tag=process.argv[2]||'before';
const pad=(r,m=8)=>({x:Math.max(0,r.x-m),y:Math.max(0,r.y-m),width:r.width+m*2,height:r.height+m*2});
const shot=async(p,sel,path)=>{
  const r=await p.evaluate(s=>{const e=document.querySelector(s);if(!e)return null;const b=e.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height};},sel);
  if(!r||r.width<2||r.height<2){console.log('MISS',sel,JSON.stringify(r));return;}
  await p.screenshot({path,clip:pad(r)});
  console.log('ok',path);
};
const b=await chromium.launch();
for(const scheme of ['light','dark']){
  const ctx=await b.newContext({viewport:{width:1600,height:1000},colorScheme:scheme});
  const p=await ctx.newPage();
  await p.goto(`${APP}/?s=fabric&d=access13&tab=ports&v=1&snap=9cc348bd58bb`,{waitUntil:'load'});
  await p.waitForTimeout(2000);
  await shot(p,'.dp__tabs',`review/_fixshots/${tag}-tabs-${scheme}.png`);
  await p.goto(`${APP}/?s=findings&f=F001&d=core1&v=1&snap=9cc348bd58bb`,{waitUntil:'load'});
  await p.waitForTimeout(1800);
  await shot(p,'.ag__cell--head',`review/_fixshots/${tag}-gridhead-${scheme}.png`);
  const r=await p.evaluate(()=>{const e=document.querySelector('[role="row"]');const b=e.getBoundingClientRect();return {x:0,y:Math.max(0,b.y-6),width:Math.min(1600,b.width+40),height:b.height+14};});
  await p.screenshot({path:`review/_fixshots/${tag}-headrow-${scheme}.png`,clip:r});
  console.log('ok headrow',scheme);
  await ctx.close();
}
await b.close();
