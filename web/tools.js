/* Meeting tools use existing transcript/task data; they never trigger an AI job. */
function renderInsights(m) {
  const info = m.insights || {speaking: [], risks: [], total_tasks: 0, reviewed: 0};
  return `<section class="insight-banner"><div><span class="eyebrow">ПОСЛЕ ВСТРЕЧИ НАЧИНАЕТСЯ ГЛАВНОЕ</span><h2>От решений к результату</h2><p>Найдите незакрытые вопросы и подготовьте следующий шаг.</p></div><span class="insight-orbit" aria-hidden="true">↗</span></section>
  <div class="tool-grid"><a class="tool-tile" href="/api/meetings/${m.id}/agenda"><span class="tool-glyph">≡</span><strong>Следующая повестка</strong><p>Открытые поручения, ответственные и вопросы для следующей встречи.</p><span class="tool-cta">Скачать Markdown ↗</span></a><a class="tool-tile" href="/api/meetings/${m.id}/calendar"><span class="tool-glyph">▦</span><strong>Поручения в календарь</strong><p>Только проверенные задачи с подтверждённой датой. Импорт в Outlook или Calendar.</p><span class="tool-cta">Скачать ICS ↗</span></a></div>
  <section class="panel radar"><div class="section-head"><h2>Радар внимания</h2><span class="badge ${info.risks.length?'amber':''}">${info.risks.length} требуют внимания</span></div><p class="subtitle">Правила проверки, а не оценка сотрудников: пропущенные ответственные, сроки и неподтверждённые решения.</p>${info.risks.length?info.risks.map(r=>`<button class="risk-row" data-task="${r.task_id}" data-mid="${m.id}"><span class="risk-dot"></span><span><strong>${esc(r.title)}</strong><small>${r.reasons.map(esc).join(' · ')}</small></span><span>↗</span></button>`).join(''):'<div class="empty"><h3>Всё проверено</h3><p>У открытых поручений нет отмеченных проблем.</p></div>'}</section>
  <section class="panel"><div class="section-head"><h2>Баланс разговора</h2><span class="badge gray">По длительности реплик</span></div>${info.has_audio_timing?`<p class="subtitle">Распределение распознанной речи между голосовыми группами. Паузы не учитываются; это не оценка продуктивности.</p><div class="speaking-chart">${info.speaking.map((s,i)=>`<div class="speaking-row"><span class="avatar tone-${i%4}">${esc(s.speaker)}</span><span class="speaking-name">${esc(s.name)}</span><meter min="0" max="100" value="${s.percent}" aria-label="Доля речи ${esc(s.name)}">${s.percent}%</meter><strong>${s.percent}%</strong><small>${clock(s.seconds)}</small></div>`).join('')}</div>`:'<p class="subtitle">Для текстового импорта длительность речи не вычисляется.</p>'}</section>
  ${m.timings?.total_seconds?`<section class="panel performance"><h2>Как обработана запись</h2><div class="timing-grid">${[['speech_seconds','Речь'],['diarization_seconds','Голоса'],['analysis_seconds','Протокол'],['total_seconds','Всего']].map(([key,label])=>`<div><small>${label}</small><strong>${m.timings[key]!==undefined?clock(m.timings[key]):'—'}</strong></div>`).join('')}</div><p class="form-help">${m.cache_hit?'Использован сохранённый результат идентичной записи с теми же настройками.':'Фактическое время обработки на этом устройстве; ожидание в очереди не включено.'}</p></section>`:''}`;
}

function transcriptSearch(m) {
  return `<div class="transcript-search"><label for="transcript-query">Найти в разговоре</label><div><input id="transcript-query" placeholder="Например: бюджет, сроки, безопасность" maxlength="300"><button id="search-transcript" class="primary">Найти</button></div><p class="form-help">Поиск по словам и их началу. Результат — исходные реплики с контекстом, без выдуманного ответа.</p><div id="transcript-results"></div></div>`;
}

function bindTranscriptSearch(m) {
  const button = $('#search-transcript');
  if (!button) return;
  let request = 0;
  const search = async () => {
    const id = ++request;
    const query = $('#transcript-query').value.trim();
    if (!query) {$('#transcript-results').innerHTML='';return;}
    button.disabled=true;
    try {
      const rows=await api(`/meetings/${m.id}/search?q=${encodeURIComponent(query)}`);
      if (id!==request || !$('#transcript-results')) return;
      $('#transcript-results').innerHTML=rows.length?rows.map(r=>`<div class="search-result"><button class="link-button" data-jump="${r.id}">${m.audio_file?clock(r.start):'#'+r.id} · ${esc(m.speakers[r.speaker]||r.speaker)} ↗</button><p>${esc(r.text)}</p><details><summary>Соседние реплики</summary>${r.context.map(c=>`<p class="form-help">#${c.id} ${esc(c.text)}</p>`).join('')}</details></div>`).join(''):'<p class="form-help">Совпадений нет. Попробуйте слова из обсуждения.</p>';
      bind('[data-jump]','click',e=>{const node=$('#segment-'+e.currentTarget.dataset.jump);if(node){$$('.segment.highlight').forEach(n=>n.classList.remove('highlight'));node.classList.add('highlight');node.scrollIntoView({behavior:'smooth',block:'center'})}});
    } catch(e){toast(e.message)} finally {button.disabled=false}
  };
  button.onclick=search;
  $('#transcript-query').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();search()}};
}

function previewMarkup(m) {
  const rows=m.segments?.length?m.segments:m.preview||[];
  if(!rows.length)return '';
  return `<section class="panel live-preview"><div class="section-head"><h2>Транскрипт уже доступен</h2><span class="badge blue">${rows.length} реплик</span></div><p class="subtitle">Можно читать, пока формируется протокол. Правки откроются после завершения.</p><div class="preview-scroll">${rows.map(s=>`<div><time>${clock(s.start)}</time><p>${esc(s.text)}</p></div>`).join('')}</div></section>`;
}

function showAddTask(m) {
  modal('Добавить поручение', `<form id="add-task-form"><p class="form-help">Если ИИ пропустил договорённость, добавьте её с основанием из транскрипта.</p><div class="form-group"><label for="new-task-title">Что нужно сделать</label><textarea id="new-task-title" required maxlength="2000" rows="3"></textarea></div><div class="form-row"><div class="form-group"><label for="new-task-owner">Ответственный</label><input id="new-task-owner" maxlength="200"></div><div class="form-group"><label for="new-task-date">Срок</label><input id="new-task-date" type="date"></div></div><div class="form-group"><label for="new-task-evidence">Номера реплик через запятую</label><input id="new-task-evidence" required placeholder="Например: 16, 17"><div class="form-help">Номер реплики можно посмотреть во вкладке «Транскрипт». Диапазон: 1–${m.segments.length}.</div></div>${errorDiv}<div class="modal-actions"><button class="primary">Добавить</button></div></form>`);
  $('#add-task-form').onsubmit=async event=>{
    event.preventDefault();
    try {
      const ids=$('#new-task-evidence').value.split(/[,\s]+/).filter(Boolean).map(Number);
      if(!ids.length || ids.some(n=>!Number.isInteger(n)||n<1))throw new Error('Введите номера реплик через запятую.');
      await api(`/meetings/${m.id}/tasks`,{method:'POST',body:{title:$('#new-task-title').value,assignee:$('#new-task-owner').value,due_date:$('#new-task-date').value||null,evidence_ids:ids}});
      closeModal();state.item=await api('/meetings/'+m.id);renderDetail();toast('Поручение добавлено. Проверьте его перед исполнением.');
    } catch(error){formError(error)}
  };
}
