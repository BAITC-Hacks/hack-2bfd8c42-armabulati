'use strict';
function deadlineTone(task, today = new Date()) {
  if (task.status === 'done') return {tone:'done', label:'Выполнено'};
  if (!/^\d{4}-\d{2}-\d{2}$/.test(task.due_date || '')) return {tone:'none',label:'Без срока'};
  const day = Date.UTC(today.getFullYear(),today.getMonth(),today.getDate());
  const [y,m,d] = task.due_date.split('-').map(Number);
  const days = Math.round((Date.UTC(y,m-1,d)-day)/86400000);
  let tone, label;
  if (days<0) {tone='overdue';label='Срок прошёл'}
  else if (days===0) {tone='today';label='Срок сегодня'}
  else if (days===1) {tone='soon';label='Срок завтра'}
  else if (days<=3) {tone='near';label=`Осталось ${days} дня`}
  else if (days<=7) {tone='week';label=`Осталось ${days} ${days===4?'дня':'дней'}`}
  else {tone='calm';label='Есть время'}
  return {tone,label:(task.date_uncertain?'Предварительно: ':'')+label};
}
if (typeof module !== 'undefined') module.exports = {deadlineTone};
