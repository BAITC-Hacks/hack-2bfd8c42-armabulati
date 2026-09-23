'use strict';
let authInfo = null;

function lockWorkspace() {
  closeModal();
  state.user=null;state.meetings=[];state.notifications=[];state.item=null;state.selected=null;
  $('#main').replaceChildren();
  document.body.classList.add('auth-locked');
}

async function authenticate() {
  try {
    authInfo = await api('/auth/session');
    state.token = authInfo.token;
    state.user = authInfo.user;
    if (!authInfo.user) {renderAuth();return false}
    document.body.classList.remove('auth-locked');
    $('#auth-root').replaceChildren();
    $$('.profile-name').forEach(el=>el.textContent=state.user.name);
    $$('.profile-avatar').forEach(el=>el.textContent=state.user.name.slice(0,2).toUpperCase());
    $('#account-button').onclick=showAccount;
    return true;
  } catch(error) {
    document.body.classList.add('auth-locked');
    $('#auth-root').innerHTML=`<section class="auth-offline"><h1>Dauys Hunt</h1><p>${esc(error.message)}</p><button class="primary" id="auth-retry">Подключиться снова</button></section>`;
    $('#auth-retry').onclick=init;
    return false;
  }
}

function renderAuth(register=false) {
  document.body.classList.add('auth-locked');
  $('#auth-root').innerHTML=`<main class="auth-layout"><section class="auth-story"><a class="auth-brand" href="/" aria-label="Dauys Hunt"><img src="/mark.svg" width="44" height="44" alt=""><span>Dauys <b>Hunt</b></span></a><span class="auth-kicker">ГОЛОС → СМЫСЛ → ДЕЙСТВИЕ</span><h1>Слышать главное.<br> <em>Доводить до дела.</em></h1><p>Ваши обсуждения становятся ясными решениями. Протокол, поручения и сроки — в одном защищённом пространстве.</p><div class="voice-visual" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div><div class="auth-proof"><span>Қазақша · Русский</span><span>Локальный ИИ</span><span>Личные записи</span></div><small>Аудио и протоколы обрабатываются на этом устройстве.<br>Социальный вход связывается только с выбранным провайдером.</small></section><section class="auth-entry"><div class="auth-card"><div class="eyebrow">ВАШЕ ПРОСТРАНСТВО РЕШЕНИЙ</div><h2>${register?'Создайте аккаунт':'С возвращением'}</h2><p>${register?'Начните с голоса. Сохраните результат.':'Войдите, чтобы продолжить работу с совещаниями.'}</p><div class="social-auth"><button type="button" data-provider="google" ${!authInfo.providers.google?'disabled':''}><span class="google-letter" aria-hidden="true">G</span> Google</button><button type="button" data-provider="facebook" ${!authInfo.providers.facebook?'disabled':''}><span class="facebook-letter" aria-hidden="true">f</span> Facebook</button></div>${!authInfo.providers.google||!authInfo.providers.facebook?'<p class="social-note">Социальный вход станет доступен после подключения администратором.</p>':''}<div class="auth-divider"><span>или через email</span></div><form id="auth-form">${register?'<label for="auth-name">Ваше имя</label><input id="auth-name" autocomplete="name" required maxlength="100" placeholder="Как к вам обращаться">':''}<label for="auth-email">Email</label><input id="auth-email" type="email" autocomplete="username" maxlength="254" required placeholder="you@example.com"><label for="auth-password">Пароль</label><div class="password-field"><input id="auth-password" type="password" autocomplete="${register?'new-password':'current-password'}" required ${register?'minlength="12"':''} maxlength="128" placeholder="${register?'Минимум 12 символов':'Введите пароль'}"><button id="password-visibility" type="button" aria-label="Показать пароль" aria-pressed="false">Показать</button></div>${register?'<p class="auth-hint">Подойдёт длинная фраза из нескольких слов. Email используется как логин; проверка почты пока не подключена.</p>':''}${register?'<label for="auth-confirm">Повторите пароль</label><input id="auth-confirm" type="password" autocomplete="new-password" required minlength="12" maxlength="128" placeholder="Введите пароль ещё раз">':''}<div id="auth-error" class="form-error hidden" role="alert"></div><button class="primary auth-submit" type="submit">${register?'Зарегистрироваться':'Войти в аккаунт'} <span aria-hidden="true">↗</span></button></form><p class="auth-switch">${register?'Уже есть аккаунт?':'Нет аккаунта?'} <button class="link-button" id="auth-switch">${register?'Войти':'Зарегистрироваться'}</button></p><p class="auth-privacy">Личная сессия · Защищённые пароли · Контроль доступа</p></div></section></main>`;
  const err=$('#auth-error');
  const showError=error=>{err.textContent=error.message;err.classList.remove('hidden')};
  if(new URLSearchParams(location.search).has('auth_error')){
    showError(new Error('Не удалось войти через сервис. Попробуйте ещё раз или используйте email.'));
    history.replaceState(null,'',location.pathname+location.hash);
  }
  $('#auth-switch').onclick=()=>renderAuth(!register);
  $('#password-visibility').onclick=event=>{
    const input=$('#auth-password'),show=input.type==='password';input.type=show?'text':'password';
    event.currentTarget.textContent=show?'Скрыть':'Показать';event.currentTarget.setAttribute('aria-pressed',String(show));event.currentTarget.setAttribute('aria-label',show?'Скрыть пароль':'Показать пароль');
  };
  $('#auth-form').onsubmit=async event=>{
    event.preventDefault();const button=$('.auth-submit');button.disabled=true;err.classList.add('hidden');
    try{
      const body={email:$('#auth-email').value,password:$('#auth-password').value};
      if(register){body.name=$('#auth-name').value;body.password_confirm=$('#auth-confirm').value;if(body.password!==body.password_confirm)throw new Error('Пароли не совпадают.')}
      const result=await api(register?'/auth/register':'/auth/login',{method:'POST',body});state.token=result.token;state.user=result.user;
      await init();
    }catch(error){showError(error)}finally{button.disabled=false}
  };
  bind('[data-provider]','click',async event=>{
    const button=event.currentTarget;button.disabled=true;
    try{const result=await api('/auth/oauth/'+button.dataset.provider+'/start',{method:'POST'});location.assign(result.url)}catch(error){showError(error);button.disabled=false}
  });
}

function showAccount() {
  modal('Ваш аккаунт',`<div class="account-summary"><span class="avatar">${esc(state.user.name.slice(0,2).toUpperCase())}</span><div><strong>${esc(state.user.name)}</strong><p>${esc(state.user.email||'Вход через '+state.user.provider)}</p></div></div><p>Ваши совещания и поручения доступны только этому аккаунту.</p>${state.user.provider==='email'?'<form id="password-form"><div class="form-group"><label for="current-password">Текущий пароль</label><input id="current-password" type="password" autocomplete="current-password" required maxlength="128"></div><div class="form-group"><label for="new-password">Новый пароль · минимум 12 символов</label><input id="new-password" type="password" autocomplete="new-password" required minlength="12" maxlength="128"></div>'+errorDiv+'<button class="secondary">Обновить пароль</button></form>':''}<div class="modal-actions"><button class="danger-button" id="logout-button">Выйти из аккаунта</button></div>`);
  if($('#password-form'))$('#password-form').onsubmit=async event=>{
    event.preventDefault();try{const result=await api('/auth/password',{method:'POST',body:{current_password:$('#current-password').value,new_password:$('#new-password').value}});state.token=result.token;closeModal();toast('Пароль обновлён. Другие сессии завершены.')}catch(error){formError(error)}
  };
  $('#logout-button').onclick=async()=>{
    try{await api('/auth/logout',{method:'POST'});lockWorkspace();await authenticate()}catch(error){formError(error)}
  };
}

