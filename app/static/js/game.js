// ===== Abakra live game engine (frontend) =====
(function () {
  const root = document.getElementById('game');
  if (!root) return;
  const MID = root.dataset.mid;
  const L = JSON.parse(root.dataset.labels);
  const IS_ADMIN = root.dataset.isAdmin === '1';
  const base = `/api/game/${MID}`;
  let state = null;
  let timer = { remaining: 30, duration: 30, running: false, handle: null, key: null };
  const NORMAL_TIMER_SECONDS = 30;
  const REBOUND_TIMER_SECONDS = 5;
  const TIMER_SOUND_URL = '/static/audio/timer-effect.mp3';
  const SPIN_SOUND_URL = '/static/audio/spinning-effect.mp3';
  const SPIN_DURATION_MS = 3000;
  const SPIN_RESULT_POPUP_MS = 2000;
  const timerAudio = makeAudio(TIMER_SOUND_URL, true);
  const spinAudio = makeAudio(SPIN_SOUND_URL, false);
  // Whether the current question's answer text is visible to the host.
  // Auto-revealed when the timer reaches 0 or when the host clicks the
  // "Show Answer" button. Reset each time a new question is revealed.
  let showAnswer = false;
  let lastQKey = null;

  const $ = (id) => document.getElementById(id);

  const DEFAULT_SECTION_ORDER = [1, 2, 5, 3, 4];

  async function call(path, body) {
    const r = await apiPost(base + path, body);
    if (r.ok) { state = r.data; render(); }
    else { flash(r.data.error, r.data.ctx); }
    return r;
  }

  function flash(key, ctx) {
    let msg = key || 'error';
    if (key === 'not_enough_questions' && ctx) msg = `${L['available']}: ${ctx.cat} (${ctx.n})`;
    (window.SmartAlert || alert)(msg);
  }

  async function refresh() {
    const r = await apiGet(base + '/state');
    if (r.ok) { state = r.data; render(); }
  }

  // ---------- render ----------
  function render() {
    if (!state) return;
    $('ta-name').textContent = state.team_a.name;
    $('tb-name').textContent = state.team_b.name;
    $('ta-score').textContent = state.score_a;
    $('tb-score').textContent = state.score_b;
    $('match-status').textContent = state.status;

    // Ready gate: while the match is scheduled / ready, hide the play surface
    // and show a big "Start Match" banner. The host must explicitly start
    // the match — opening the page is non-destructive.
    const notStarted = (state.status === 'scheduled' || state.status === 'ready');
    const completed = state.status === 'completed';
    $('scoreboard-card').classList.toggle('hidden', !completed);
    $('ready-banner').classList.toggle('hidden', !notStarted);
    $('finished-banner').classList.toggle('hidden', !completed);
    if ($('finished-score')) {
      $('finished-score').textContent = `${state.team_a.name} ${state.score_a} - ${state.score_b} ${state.team_b.name}`;
    }
    $('section-controls-card').classList.toggle('hidden', notStarted || completed);
    $('qcard-wrap').classList.toggle('hidden', notStarted || completed);
    $('match-summary-grid').classList.toggle('hidden', !completed);
    document.getElementById('section-tabs').classList.toggle('hidden', notStarted || completed);
    // Pause / return-to-ready button visibility.
    $('btn-pause-match').classList.toggle('hidden', notStarted || completed);
    $('btn-reset-ready').classList.toggle('hidden', notStarted || completed);
    $('btn-complete').classList.toggle('hidden', notStarted || completed);

    if (notStarted) {
      // Nothing else to render while awaiting Start.
      $('btn-pause-match').textContent = L['pause_match'];
      $('btn-complete').textContent = L['complete'];
      return;
    }

    if (completed) {
      stopTimer();
      renderRemaining();
      renderHistory();
      if (IS_ADMIN && $('btn-reset-usage')) $('btn-reset-usage').textContent = L['reset_usage'];
      return;
    }

    renderTabs();
    renderSectionControls();
    renderQuestion();
    renderRemaining();
    renderHistory();
    $('btn-pause-match').textContent = state.status === 'paused' ? L['resume_match'] : L['pause_match'];
    $('btn-complete').textContent = L['complete'];
    if (IS_ADMIN && $('btn-reset-usage')) $('btn-reset-usage').textContent = L['reset_usage'];
  }

  function renderTabs() {
    const el = $('section-tabs');
    el.innerHTML = '';
    sectionOrder().forEach((s, i) => {
      const div = document.createElement('div');
      div.className = 'tab';
      if (state.current_section === s) div.classList.add('active');
      if (state.sections[s] && state.sections[s].completed) div.classList.add('done');
      div.textContent = `${i + 1}. ${sectionName(s)}`;
      el.appendChild(div);
    });
  }

  function btn(label, cls, onclick, disabled) {
    const b = document.createElement('button');
    b.className = 'btn ' + (cls || '');
    b.textContent = label;
    if (disabled) b.disabled = true;
    b.onclick = onclick;
    return b;
  }

  function renderSectionControls() {
    const el = $('section-controls');
    el.innerHTML = '';
    const sec = state.current_section;
    // section start buttons
    const bar = document.createElement('div');
    bar.className = 'controls';
    sectionOrder().forEach((s, i) => {
      const done = state.sections[s] && state.sections[s].completed;
      bar.appendChild(btn(`${L['start_section']} ${i + 1}`, done ? 'ghost' : (sec === s ? 'primary' : ''),
        () => call('/start-section', { section: s })));
    });
    el.appendChild(bar);

    if (!sec || !state.sections[sec]) return;
    const busy = state.current && state.current.phase && state.current.phase !== 'done';
    const secType = sectionType(sec);

    if (secType === 4) { renderWheel(el, busy, sec); return; }
    if (secType === 5) {
      const b = btn(`${L['reveal']} — ${sectionName(sec)}`, 'primary',
        () => call('/select', { section: sec, category_id: state.special_category_id, team: null }), busy);
      el.appendChild(b);
      return;
    }

    // Regular question sections: section type 1 needs team choice.
    const wrap = document.createElement('div');
    wrap.className = 'cat-chips mt';
    state.remaining.forEach(c => {
      if (secType === 1) {
        ['a', 'b'].forEach(team => {
          const chip = mkChip(`${c.name} — ${team === 'a' ? state.team_a.name : state.team_b.name} (${c.remaining})`,
            c.remaining <= 0 || busy, () => call('/select', { section: sec, category_id: c.id, team }));
          wrap.appendChild(chip);
        });
      } else {
        const chip = mkChip(`${c.name} (${c.remaining})`, c.remaining <= 0 || busy,
          () => call('/select', { section: sec, category_id: c.id, team: null }));
        wrap.appendChild(chip);
      }
    });
    el.appendChild(wrap);

    el.appendChild(btn(L['finish_section'], 'ghost mt', () => call('/finish-section', { section: sec })));
  }

  function mkChip(text, disabled, onclick) {
    const d = document.createElement('div');
    d.className = 'cat-chip' + (disabled ? ' empty' : '');
    d.textContent = text;
    if (!disabled) d.onclick = onclick;
    return d;
  }

  // ---------- question panel ----------
  function renderQuestion() {
    const qc = $('qcard');
    const ctrl = $('q-controls');
    ctrl.innerHTML = '';
    const cur = state.current;
    const showTimer = Boolean(cur && cur.phase !== 'done');
    $('timer-box').classList.toggle('hidden', !showTimer);
    $('timer-controls').classList.toggle('hidden', !showTimer);

    if (!cur) {
      stopTimer();
      timer.key = null;
      qc.innerHTML = `<div class="question-panel is-empty"><p class="muted">-</p></div>`;
      updateTimerDisplay();
      return;
    }
    const c = cur.content || {};
    // Reset the local "show answer" gate whenever we move to a new question
    // or the question is not yet revealed.
    const qKey = `${cur.section || ''}:${c.code || ''}:${cur.phase || ''}`;
    if (cur.phase === 'selected') { showAnswer = false; }
    else if (qKey !== lastQKey && cur.phase === 'revealed') { showAnswer = false; }
    // Once the host has scored the question, phase moves past 'revealed'
    // (e.g. rebound_open, done). In those phases the answer is safe to show.
    const answerUnlocked = showAnswer || (cur.phase && cur.phase !== 'selected' && cur.phase !== 'revealed');
    lastQKey = qKey;
    if (showTimer) {
      ensureTimerForCurrentQuestion(cur, c);
      setupTimerButtons();
    } else {
      stopTimer();
    }
    qc.innerHTML = renderQuestionPanel(cur, c, answerUnlocked);

    const sec = cur.section;
    const secType = Number(cur.section_type || sectionType(sec));
    if (cur.phase === 'selected') {
      ctrl.appendChild(btn(L['reveal'], 'primary', () => call('/reveal', {})));
      ctrl.appendChild(btn(L['skip'], 'ghost', () => call('/mark', { action: 'skip' })));
      return;
    }
    if (cur.phase === 'revealed' && !showAnswer) {
      // Host can force-reveal the answer any time before scoring.
      ctrl.appendChild(btn(L['show_answer'] || 'Show Answer', 'primary', () => { showAnswer = true; render(); }));
    }
    if (cur.phase === 'revealed') {
      if (secType === 5) {
        ctrl.appendChild(btn(`${L['father_a']} (+10)`, 'success', () => call('/mark', { action: 'father_a' })));
        ctrl.appendChild(btn(`${L['father_b']} (+10)`, 'success', () => call('/mark', { action: 'father_b' })));
        ctrl.appendChild(btn(L['no_answer'], 'ghost', () => call('/mark', { action: 'father_none' })));
      } else if (secType === 1 || secType === 4) {
        // assigned-team sections: correct on the assigned team only
        const team = cur.team;
        ctrl.appendChild(btn(L[team === 'a' ? 'a_correct' : 'b_correct'] + ' (+5)', 'success',
          () => call('/mark', { action: team === 'a' ? 'a_correct' : 'b_correct' })));
        ctrl.appendChild(btn(L['wrong'] + ' → ' + L['open_rebound'], 'danger', () => call('/mark', { action: 'wrong' })));
      } else if (secType === 2) {
        // buzzer decides who answers; both correct buttons available
        ctrl.appendChild(btn(L['a_correct'] + ' (+5)', 'success', () => call('/mark', { action: 'a_correct' })));
        ctrl.appendChild(btn(L['b_correct'] + ' (+5)', 'success', () => call('/mark', { action: 'b_correct' })));
        ctrl.appendChild(btn(L['wrong'] + ' → ' + L['open_rebound'], 'danger', () => call('/mark', { action: 'wrong' })));
      } else if (secType === 3) {
        // individual: no rebound
        ctrl.appendChild(btn(L['a_correct'] + ' (+5)', 'success', () => call('/mark', { action: 'a_correct' })));
        ctrl.appendChild(btn(L['b_correct'] + ' (+5)', 'success', () => call('/mark', { action: 'b_correct' })));
        ctrl.appendChild(btn(L['wrong'] + ' (0/0)', 'danger', () => call('/mark', { action: 'wrong' })));
      }
      ctrl.appendChild(btn(L['skip'], 'ghost', () => call('/mark', { action: 'skip' })));
      ctrl.appendChild(btn(L['invalidate'], 'ghost', async () => {
        const reason = (await window.SmartPrompt(L['invalidate_reason'])) || '';
        // Cancel closes the dialog without a call.
        if (reason === null) return;
        call('/mark', { action: 'invalidate', reason });
      }));
      return;
    }
    if (cur.phase === 'rebound_open') {
      ctrl.appendChild(btn(L['rebound_correct'] + ' (+10)', 'success', () => call('/mark', { action: 'rebound_correct' })));
      ctrl.appendChild(btn(L['rebound_wrong'] + ' (0)', 'danger', () => call('/mark', { action: 'rebound_wrong' })));
      return;
    }
  }

  function renderQuestionPanel(cur, c, answerUnlocked) {
    const kind = questionKind(c);
    const teamName = cur.team ? (cur.team === 'a' ? state.team_a.name : state.team_b.name) : '';
    const meta = [cur.category_name, c.code, teamName].filter(Boolean).map(escapeHtml).join(' · ');
    const panelClasses = ['question-panel', `question-kind-${kind}`];
    if (cur.phase === 'selected') panelClasses.push('is-waiting');
    if (cur.phase === 'rebound_open') panelClasses.push('is-rebound');

    let html = `<div class="${panelClasses.join(' ')}">`;
    if (meta) html += `<div class="question-meta">${meta}</div>`;
    const questionText = cur.phase === 'selected' ? `${L['reveal']}?` : (c.text || '');
    html += `<div class="question-banner"><p class="qtext">${escapeHtml(questionText)}</p></div>`;

    if (cur.phase !== 'selected') {
      const displayedChoices = choicesForKind(c, kind);
      if (displayedChoices.length) {
        html += `<div class="question-choices choice-count-${displayedChoices.length}">`;
        html += displayedChoices.map(ch => `<div class="question-choice">${escapeHtml(ch)}</div>`).join('');
        html += '</div>';
      }
      if (answerUnlocked) {
        html += '<div class="answer-panel">';
        if (c.answer) html += `<p><strong>${L['correct_answer']}:</strong> ${escapeHtml(c.answer)}</p>`;
        if (c.explanation) html += `<p class="muted">${L['explanation']}: ${escapeHtml(c.explanation)}</p>`;
        html += '</div>';
      }
    }
    html += '</div>';
    return html;
  }

  function questionKind(c) {
    if (c.qtype === 'mc') return 'mc';
    if (c.qtype === 'tf') return 'tf';
    return 'open';
  }

  function choicesForKind(c, kind) {
    const choices = c.choices || [];
    if (kind === 'mc') return choices.slice(0, 4);
    if (kind === 'tf') return choices.slice(0, 2);
    return [];
  }

  // ---------- wheel ----------
  function renderWheel(el, busy, sectionId) {
    const w = state.wheel || { spins_a: 3, spins_b: 3, turn: 'a' };
    const box = document.createElement('div');
    box.className = 'wheel-wrap mt';
    box.innerHTML = `<div class="wheel-pointer"></div>
      <div class="wheel" id="wheel-el"></div>
      <p>${L['current_turn']}: <strong>${w.turn === 'a' ? state.team_a.name : state.team_b.name}</strong></p>
      <p class="muted">${L['spins_a']}: ${w.spins_a} · ${L['spins_b']}: ${w.spins_b}</p>`;
    el.appendChild(box);
    drawWheel($('wheel-el') || box.querySelector('.wheel'));

    const bar = document.createElement('div');
    bar.className = 'controls';
    bar.appendChild(btn(`${L['spin']} — ${state.team_a.name}`, 'primary',
      () => doSpin('a'), busy || w.spins_a <= 0));
    bar.appendChild(btn(`${L['spin']} — ${state.team_b.name}`, 'primary',
      () => doSpin('b'), busy || w.spins_b <= 0));
    el.appendChild(bar);
    el.appendChild(btn(L['finish_section'], 'ghost mt', () => call('/finish-section', { section: sectionId })));

    if (state.last_spin) {
      const info = document.createElement('p');
      info.className = 'mt';
      info.innerHTML = `<strong>${state.last_spin.team === 'a' ? state.team_a.name : state.team_b.name}</strong> → <span style="color:var(--accent-light)">${state.last_spin.result}</span>`;
      el.appendChild(info);
    }
  }

  function drawWheel(elm) {
    if (!elm) return;
    const segs = state.remaining.map(c => c.name).concat(['الجوكر']);
    const n = segs.length;
    const colors = ['#123a6b', '#2b9fd6', '#e8821e', '#7a1620', '#2e9d63', '#d9a938'];
    let stops = [];
    for (let i = 0; i < n; i++) {
      stops.push(`${colors[i % colors.length]} ${(i * 360 / n)}deg ${((i + 1) * 360 / n)}deg`);
    }
    elm.style.background = `conic-gradient(${stops.join(',')})`;
  }

  async function doSpin(team) {
    const wheelEl = document.querySelector('.wheel');
    if (wheelEl) wheelEl.style.transform = `rotate(${1440 + Math.random() * 360}deg)`;
    playSound(spinAudio, true);
    const r = await apiPost(base + '/spin', { team });
    if (!r.ok) { stopSound(spinAudio); flash(r.data.error); return; }
    state = r.data;
    const spin = state.last_spin;
    setTimeout(() => stopSound(spinAudio), SPIN_DURATION_MS);
    setTimeout(() => {
      showSpinResultPopup(spin, () => {
        if (spin && spin.result === 'الجوكر') {
          openJokerDialog(team);
        } else if (spin) {
          const cat = state.remaining.find(c => c.name === spin.result);
          if (cat && cat.remaining > 0) {
            call('/select', { section: state.current_section, category_id: cat.id, team });
          } else {
            render();
            window.SmartAlert(L['not_enough_questions'] + ': ' + spin.result);
          }
        } else render();
      });
    }, SPIN_DURATION_MS);
  }

  function showSpinResultPopup(spin, afterClose) {
    if (!spin) {
      afterClose();
      return;
    }
    const root = $('modal-root');
    const teamName = spin.team === 'a' ? state.team_a.name : state.team_b.name;
    root.innerHTML = `<div class="modal-backdrop spin-result-backdrop">
      <div class="spin-result-modal">
        <div class="spin-result-label">${escapeHtml(teamName)}</div>
        <div class="spin-result-value">${escapeHtml(spin.result)}</div>
      </div>
    </div>`;
    setTimeout(() => {
      root.innerHTML = '';
      afterClose();
    }, SPIN_RESULT_POPUP_MS);
  }

  function openJokerDialog(team) {
    const root = $('modal-root');
    root.innerHTML = `<div class="modal-backdrop"><div class="modal">
      <h3>${L['joker_select']}</h3><div class="cat-chips mt" id="joker-cats"></div>
      <div class="controls mt"><button class="btn ghost" id="joker-cancel">${L['cancel']}</button></div>
    </div></div>`;
    const cc = $('joker-cats');
    state.remaining.forEach(c => {
      cc.appendChild(mkChip(`${c.name} (${c.remaining})`, c.remaining <= 0, () => {
        root.innerHTML = '';
        call('/select', { section: state.current_section, category_id: c.id, team, via_joker: true });
      }));
    });
    $('joker-cancel').onclick = () => { root.innerHTML = ''; render(); };
  }

  // ---------- remaining + history ----------
  function renderRemaining() {
    $('remaining-list').innerHTML = state.remaining.map(c =>
      `<div class="row" style="justify-content:space-between"><span>${c.name}</span><span class="rem">${c.remaining}</span></div>`).join('');
  }
  function renderHistory() {
    $('history-list').innerHTML = state.history.map(h => {
      const who = h.team === 'a' ? state.team_a.name : h.team === 'b' ? state.team_b.name : '—';
      const sign = h.delta > 0 ? '+' : '';
      return `<div class="row" style="justify-content:space-between"><span class="muted">${h.reason}</span><span>${who} ${sign}${h.delta}</span></div>`;
    }).join('');
  }

  // ---------- timer (client, host-controlled) ----------
  function timerDurationFor(cur) {
    return cur && cur.phase === 'rebound_open' ? REBOUND_TIMER_SECONDS : NORMAL_TIMER_SECONDS;
  }

  function timerKeyFor(cur, c) {
    if (!cur) return null;
    return [cur.section || '', cur.question_id || c.id || c.code || '', cur.phase || ''].join(':');
  }

  function ensureTimerForCurrentQuestion(cur, c) {
    const nextKey = timerKeyFor(cur, c);
    const nextDuration = timerDurationFor(cur);
    if (timer.key !== nextKey || timer.duration !== nextDuration) {
      stopTimer();
      timer.key = nextKey;
      timer.duration = nextDuration;
      timer.remaining = nextDuration;
    }
    updateTimerDisplay();
  }

  function setupTimerButtons() {
    const startLabel = timer.remaining < timer.duration ? L['resume_timer'] : L['start_timer'];
    $('t-start').textContent = startLabel;
    $('t-reset').textContent = L['reset_timer'];
    $('t-pause').textContent = L['pause_timer'];
    $('t-start').disabled = timer.running;
    $('t-pause').disabled = !timer.running;
    $('t-start').onclick = startTimer;
    $('t-pause').onclick = () => { stopTimer(); };
    $('t-reset').onclick = resetTimer;
    updateTimerDisplay();
  }

  function startTimer() {
    if (timer.running) return;
    if (timer.remaining <= 0) timer.remaining = timer.duration;
    timer.running = true;
    playSound(timerAudio, true);
    setupTimerButtons();
    timer.handle = setInterval(() => {
      timer.remaining = Math.max(0, timer.remaining - 1);
      updateTimerDisplay();
      if (timer.remaining <= 0) {
        stopTimer();
        // Timer expired: unlock the answer for the host automatically.
        if (state.current && state.current.phase !== 'selected' && !showAnswer) {
          showAnswer = true;
          render();
        }
      }
    }, 1000);
  }

  function stopTimer() {
    timer.running = false;
    if (timer.handle) clearInterval(timer.handle);
    timer.handle = null;
    stopSound(timerAudio);
    if ($('t-start')) {
      const startLabel = timer.remaining < timer.duration ? L['resume_timer'] : L['start_timer'];
      $('t-start').textContent = startLabel;
      $('t-start').disabled = false;
    }
    if ($('t-pause')) $('t-pause').disabled = true;
    updateTimerDisplay();
  }

  function resetTimer() {
    stopTimer();
    timer.remaining = timer.duration;
    updateTimerDisplay();
    setupTimerButtons();
  }

  function updateTimerDisplay() {
    if (!$('timer-display')) return;
    $('timer-display').textContent = timer.remaining;
    const ratio = timer.duration > 0 ? timer.remaining / timer.duration : 0;
    const angle = Math.max(0, Math.min(360, ratio * 360));
    if ($('timer-box')) {
      $('timer-box').style.setProperty('--timer-angle', `${angle}deg`);
      $('timer-box').classList.toggle('is-low', timer.remaining <= Math.ceil(timer.duration / 3));
      $('timer-box').classList.toggle('is-empty', timer.remaining <= 0);
    }
  }

  function makeAudio(src, loop) {
    const audio = new Audio(src);
    audio.loop = loop;
    audio.preload = 'auto';
    return audio;
  }

  function playSound(audio, restart) {
    if (!audio) return;
    if (restart) {
      try { audio.currentTime = 0; } catch (_) {}
    }
    audio.play().catch(() => {});
  }

  function stopSound(audio) {
    if (!audio) return;
    audio.pause();
    try { audio.currentTime = 0; } catch (_) {}
  }

  // ---------- match controls ----------
  $('btn-pause-match').onclick = () => call(state.status === 'paused' ? '/resume' : '/pause', {});
  $('btn-complete').onclick = async () => {
    const r = await apiPost(base + '/complete', {});
    if (r.ok) { state = r.data; render(); window.SmartAlert(L['complete'] + ' ✓'); }
    else if (r.data.error === 'knockout_no_draw') { openWinnerDialog(); }
    else flash(r.data.error);
  };
  // Explicit start: flips scheduled/ready → in_progress.
  if ($('btn-start-match')) {
    $('btn-start-match').onclick = () => call('/start', {});
  }
  // Return-to-ready: rolls in_progress/paused back so the host can start
  // over. Uses the shared data-confirm handler for the confirmation dialog.
  if ($('btn-reset-ready')) {
    $('btn-reset-ready').onclick = () => {
      // Skip when the button is hidden — safety net if a stale click bubbles.
      if ($('btn-reset-ready').classList.contains('hidden')) return;
      const msg = $('btn-reset-ready').dataset.confirm || L['return_to_ready'];
      window.SmartConfirm(
        { message: msg, okLabel: L['return_to_ready'], okKind: 'primary' },
        async () => {
          const r = await apiPost(base + '/reset-to-ready', {});
          if (r.ok) { state = r.data; render(); }
          else { flash(r.data.error); }
        },
      );
    };
  }
  if (IS_ADMIN && $('btn-reset-usage')) {
    $('btn-reset-usage').onclick = () => {
      window.SmartConfirm(
        { message: L['reset_usage_confirm'], okKind: 'danger' },
        async () => {
          await apiPost(base + '/reset-usage', {});
          refresh();
        },
      );
    };
  }
  function openWinnerDialog() {
    const root = $('modal-root');
    root.innerHTML = `<div class="modal-backdrop"><div class="modal">
      <h3>${L['knockout_no_draw']}</h3><p>${L['select_winner']}</p>
      <div class="controls mt">
        <button class="btn success" id="win-a">${state.team_a.name}</button>
        <button class="btn success" id="win-b">${state.team_b.name}</button>
        <button class="btn ghost" id="win-cancel">${L['cancel']}</button>
      </div></div></div>`;
    $('win-a').onclick = () => finishForced('a');
    $('win-b').onclick = () => finishForced('b');
    $('win-cancel').onclick = () => { root.innerHTML = ''; };
  }
  async function finishForced(side) {
    $('modal-root').innerHTML = '';
    const r = await apiPost(base + '/complete', { winner_side: side });
    if (r.ok) { state = r.data; render(); }
  }

  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
  }

  function sectionOrder() {
    const raw = state && Array.isArray(state.section_order) && state.section_order.length
      ? state.section_order : DEFAULT_SECTION_ORDER;
    return raw.map(Number);
  }

  function sectionType(sectionId) {
    return Number((state.section_types || {})[sectionId] || sectionId);
  }

  function sectionName(sectionId) {
    return (state.section_names || {})[sectionId] || `#${sectionId}`;
  }

  // poll for external changes
  refresh();
  setInterval(() => { if (document.visibilityState === 'visible') refresh(); }, 5000);
})();
