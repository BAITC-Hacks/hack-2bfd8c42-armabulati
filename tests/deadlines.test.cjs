const test=require('node:test');
const assert=require('node:assert/strict');
const {deadlineTone}=require('../web/deadlines.js');
const today=new Date(2026,8,23,23,59);
test('urgency increases toward due day with human readable labels',()=>{
  for(const [due,tone] of [['2026-10-20','calm'],['2026-09-29','week'],['2026-09-26','near'],['2026-09-24','soon'],['2026-09-23','today'],['2026-09-22','overdue']]){
    const result=deadlineTone({due_date:due,status:'todo'},today);assert.equal(result.tone,tone);assert.ok(result.label.length);
  }
});
test('completed and undated tasks do not raise false urgency',()=>{
  assert.equal(deadlineTone({due_date:'2020-01-01',status:'done'},today).tone,'done');
  assert.equal(deadlineTone({status:'todo'},today).tone,'none');
  assert.match(deadlineTone({due_date:'2026-09-24',date_uncertain:true},today).label,/Предварительно/);
});
test('calendar-day calculation works across month/year and ignores time of day',()=>{
  assert.equal(deadlineTone({due_date:'2027-01-01'},new Date(2026,11,31)).tone,'soon');
  assert.equal(deadlineTone({due_date:'2026-09-24'},new Date(2026,8,23,0,1)).tone,'soon');
});
