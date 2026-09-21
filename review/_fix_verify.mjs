import { chromium } from '@playwright/test';
const APP='http://localhost:4180';
const b=await chromium.launch();
const p=await (await b.newContext({viewport:{width:1600,height:1000}})).newPage();
await p.goto(`${APP}/?s=findings&f=F001&d=core1&v=1&snap=9cc348bd58bb`,{waitUntil:'load'});
await p.waitForTimeout(1800);

const geom=await p.evaluate(()=>{const g=document.querySelector('[role="grid"]');const h=g.querySelector('.ag__head');
 const r=g.querySelector('.ag__row--data');
 return {clientH:g.clientHeight, headH:Math.round(h.getBoundingClientRect().height), rowH:+r.getBoundingClientRect().height.toFixed(1)};});
const visible=Math.floor((geom.clientH-geom.headH)/geom.rowH);
console.log('geometry',JSON.stringify(geom),'visibleRows',visible,'expected step',visible-1);

// drive PageDown/PageUp from the grid
await p.evaluate(()=>{const c=document.querySelector('[role="grid"] [role="rowheader"][tabindex="0"],[role="grid"] [role="gridcell"][tabindex="0"]');(c||document.querySelector('[role="grid"] [role="rowheader"]')).focus();});
const idx=()=>p.evaluate(()=>{const c=document.activeElement;const r=c.closest('[role="row"]');return r?r.getAttribute('aria-rowindex'):null;});
const trace=[await idx()];
for(let i=0;i<3;i++){await p.keyboard.press('PageDown');await p.waitForTimeout(120);trace.push(await idx());}
for(let i=0;i<2;i++){await p.keyboard.press('PageUp');await p.waitForTimeout(120);trace.push(await idx());}
console.log('rowindex trace (3x PageDown, 2x PageUp):',JSON.stringify(trace));

// aria-current + aria-selected separation
await p.keyboard.press('Enter'); await p.waitForTimeout(400);
console.log('after Enter:',JSON.stringify(await p.evaluate(()=>{const r=document.activeElement.closest('[role="row"]');
 return {url:location.search,ariaCurrent:r.getAttribute('aria-current'),ariaSelected:r.getAttribute('aria-selected'),dataActive:r.getAttribute('data-active'),
  totalCurrent:document.querySelectorAll('[role="row"][aria-current]').length};})));
await p.keyboard.press('x'); await p.waitForTimeout(300);
console.log('after x (batch):',JSON.stringify(await p.evaluate(()=>{const r=document.querySelector('[role="row"][aria-current]');
 return {ariaCurrent:r.getAttribute('aria-current'),ariaSelected:r.getAttribute('aria-selected'),dataBatched:r.getAttribute('data-batched')};})));

// sort control exposure
console.log('sortbtn:',JSON.stringify(await p.evaluate(()=>{const h=document.querySelector('[role="columnheader"][data-col="id"]');const btn=h.querySelector('.ag__sortbtn');
 return {headerLabel:h.getAttribute('aria-label'),headerAriaSort:h.getAttribute('aria-sort'),btnAriaHidden:btn.getAttribute('aria-hidden'),btnLabel:btn.getAttribute('aria-label'),
  anyAriaHiddenFocusable:[...document.querySelectorAll('a[href],button,input,select,textarea,[tabindex]')].filter(e=>e.getAttribute('tabindex')!=='-1'&&e.closest('[aria-hidden="true"]')).length};})));
await b.close();
