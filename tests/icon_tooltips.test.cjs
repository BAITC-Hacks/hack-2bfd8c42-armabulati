const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');

function harness() {
  let now=0, next=0;
  const events={}, timers=new Map(), attributes=new Map();
  const tooltip={hidden:true,style:{},textContent:'',opened:false,
    setAttribute(name,value){this[name]=value},
    matches(){return this.opened},showPopover(){this.opened=true},hidePopover(){this.opened=false},
    getBoundingClientRect(){return {width:130,height:35}}};
  const target={isConnected:true,dataset:{tooltip:'Совещания'},
    closest(){return this},contains(node){return node===this},
    getBoundingClientRect(){return {left:0,top:10,bottom:40,width:40,height:30}},
    setAttribute(key,value){attributes.set(key,value)},getAttribute(key){return attributes.get(key)},removeAttribute(key){attributes.delete(key)}};
  const context={document:{createElement:()=>tooltip,body:{append(){}},addEventListener:(name,fn)=>events[name]=fn},
    window:{addEventListener:(name,fn)=>events[name]=fn},innerWidth:390,innerHeight:600,
    setTimeout:(fn,delay)=>{const id=++next;timers.set(id,{fn,at:now+delay});return id},clearTimeout:id=>timers.delete(id)};
  vm.runInNewContext(readFileSync('web/icons.js','utf8'),context);
  return {tooltip,target,attributes,events,tick(delta){now+=delta;for(const [id,timer] of [...timers])if(timer.at<=now){timers.delete(id);timer.fn()}}};
}

test('tooltip appears after exactly 1500 ms and stays within viewport',()=>{
  const h=harness();h.events.pointerover({pointerType:'mouse',target:h.target});
  h.tick(1499);assert.equal(h.tooltip.hidden,true);
  h.tick(1);assert.equal(h.tooltip.hidden,false);assert.equal(h.tooltip.textContent,'Совещания');
  assert.equal(h.tooltip.style.left,'8px');assert.equal(h.attributes.get('aria-describedby'),'icon-tooltip');
});

test('leaving an icon cancels a pending tooltip',()=>{
  const h=harness();h.events.pointerover({pointerType:'mouse',target:h.target});
  h.tick(700);h.events.pointerout({relatedTarget:null});h.tick(2000);assert.equal(h.tooltip.hidden,true);
});

test('keyboard focus shows tooltip and Escape dismisses it',()=>{
  const h=harness();h.events.keydown({key:'Tab'});h.events.focusin({target:h.target});h.tick(1500);
  assert.equal(h.tooltip.hidden,false);h.events.keydown({key:'Escape'});
  assert.equal(h.tooltip.hidden,true);assert.equal(h.attributes.has('aria-describedby'),false);
});

test('touch input and detached icons do not produce a stuck tooltip',()=>{
  const h=harness();h.events.pointerover({pointerType:'touch',target:h.target});h.tick(1600);assert.equal(h.tooltip.hidden,true);
  h.events.pointerover({pointerType:'mouse',target:h.target});h.target.isConnected=false;h.tick(1600);assert.equal(h.tooltip.hidden,true);
});
