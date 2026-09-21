import { chromium } from '@playwright/test';
const b=await chromium.launch();
const p=await (await b.newContext({viewport:{width:1600,height:1000}})).newPage();
await p.goto('http://localhost:4180/?s=fabric&d=access13&tab=ports&v=1&snap=9cc348bd58bb',{waitUntil:'load'});
await p.waitForTimeout(2000);
console.log(JSON.stringify(await p.evaluate(()=>{
  const t=document.querySelector('[role="tablist"]');
  return {tablistCls:t?t.className:null, box:t?[Math.round(t.getBoundingClientRect().width),Math.round(t.getBoundingClientRect().height)]:null,
   dpTabs:!!document.querySelector('.dp__tabs'), allTablists:[...document.querySelectorAll('[role="tablist"]')].map(x=>x.className)};
})));
await b.close();
