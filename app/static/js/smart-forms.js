/* Abakra — shared "smart" form/UI helpers.
   Auto-wires opt-in behavior via data-* attributes so templates stay clean.

   Enable per element with:
     data-tag-adder            → smart list (bulk paste, dedupe, count, feedback)
     data-file-picker          → themed golden file button + filename span
     data-confirm="..."        → in-page confirmation modal on submit / click
     data-filter="#tableId"    → live-filter <tr>s of the given table
     data-reveal-password      → eye toggle for a password input
*/
(function () {
  'use strict';

  // ==== shared modal root ==================================================
  function getModalRoot() {
    let root = document.getElementById('__smart_modal_root');
    if (!root) {
      root = document.createElement('div');
      root.id = '__smart_modal_root';
      document.body.appendChild(root);
      root.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal-backdrop')) closeModal();
      });
    }
    return root;
  }
  function closeModal() {
    const root = document.getElementById('__smart_modal_root');
    if (root) root.innerHTML = '';
  }
  window.SmartCloseModal = closeModal;

  // ==== helpers ============================================================
  const SPLIT_REGEX = /[\n\r,،;]+/;
  function normalize(v) { return String(v || '').replace(/\s+/g, ' ').trim(); }
  function keyOf(v) { return normalize(v).toLocaleLowerCase('ar'); }

  function flashFeedback(el, msg, kind) {
    if (!el) return;
    el.textContent = msg || '';
    el.className = 'member-feedback' + (kind ? ' ' + kind : '');
    if (el._t) clearTimeout(el._t);
    if (msg) {
      el._t = setTimeout(() => { el.textContent = ''; el.className = 'member-feedback'; }, 3000);
    }
  }

  // ==== 1) tag / list adder ================================================
  // Container:
  //   <div data-tag-adder
  //        data-name="member_names"
  //        data-placeholder="اسم"
  //        data-add-label="+ إضافة"
  //        data-add-word-singular="عنصر"
  //        data-add-word-plural="عناصر"
  //        data-initial='["one","two"]'>
  //   </div>
  function initTagAdder(container) {
    if (container._init) return;
    container._init = true;

    const name       = container.dataset.name || 'items';
    const placeholder= container.dataset.placeholder || '';
    const addLabel   = container.dataset.addLabel || '+ إضافة';
    const wordSing   = container.dataset.addWordSingular || 'عنصر';
    const wordPlur   = container.dataset.addWordPlural   || 'عناصر';
    let initial = [];
    try { initial = JSON.parse(container.dataset.initial || '[]'); }
    catch (_) { initial = []; }

    container.classList.add('tag-adder');
    container.innerHTML =
      '<div class="member-add-box">' +
        '<input type="text" class="ta-input" placeholder="' + placeholder + ' — يمكن لصق عدة قيم" autocomplete="off" />' +
        '<button class="btn sm ghost ta-add-btn" type="button">' + addLabel + '</button>' +
      '</div>' +
      '<div class="member-feedback ta-feedback" aria-live="polite"></div>' +
      '<div class="members-editor mt ta-list"></div>' +
      '<div class="ta-meta"><span class="member-count-badge ta-count">0</span></div>';

    const input     = container.querySelector('.ta-input');
    const addBtn    = container.querySelector('.ta-add-btn');
    const listEl    = container.querySelector('.ta-list');
    const feedback  = container.querySelector('.ta-feedback');
    const countEl   = container.querySelector('.ta-count');

    function updateCount() {
      countEl.textContent = String(listEl.querySelectorAll('input[data-tag]').length);
    }
    function currentKeys() {
      const set = new Set();
      listEl.querySelectorAll('input[data-tag]').forEach((f) => {
        const k = keyOf(f.value); if (k) set.add(k);
      });
      return set;
    }
    function buildRow(value) {
      const row = document.createElement('div');
      row.className = 'member-row';
      row.innerHTML =
        '<input name="' + name + '" data-tag placeholder="' + placeholder + '" required />' +
        '<div class="member-row-actions"><button class="btn sm danger" type="button">حذف</button></div>';
      const field = row.querySelector('input');
      field.value = normalize(value);
      field.addEventListener('input', () => {
        const k = keyOf(field.value); let dup = false;
        listEl.querySelectorAll('input[data-tag]').forEach((other) => {
          if (other !== field && keyOf(other.value) === k && k) dup = true;
        });
        row.classList.toggle('member-row-duplicate', dup);
      });
      row.querySelector('button').addEventListener('click', () => {
        row.remove(); updateCount();
      });
      return row;
    }
    function addMany(raw) {
      const parts = String(raw || '').split(SPLIT_REGEX).map(normalize).filter(Boolean);
      if (!parts.length) { input.focus(); return; }
      const keys = currentKeys();
      const dups = []; let added = 0;
      parts.forEach((v) => {
        const k = keyOf(v);
        if (keys.has(k)) { dups.push(v); return; }
        keys.add(k); listEl.appendChild(buildRow(v)); added += 1;
      });
      updateCount();
      if (added && dups.length) flashFeedback(feedback, 'تمت إضافة ' + added + ' — تجاهل مكرر: ' + dups.join('، '), 'warn');
      else if (!added && dups.length) flashFeedback(feedback, 'موجود مسبقاً: ' + dups.join('، '), 'error');
      else if (added) flashFeedback(feedback, 'تمت إضافة ' + added + ' ' + (added > 1 ? wordPlur : wordSing), 'ok');
    }
    function addFromInput() {
      const v = input.value;
      addMany(v);
      input.value = '';
      input.focus();
    }

    addBtn.addEventListener('click', addFromInput);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); addFromInput(); }
    });
    input.addEventListener('paste', (e) => {
      const text = (e.clipboardData || window.clipboardData).getData('text');
      if (text && SPLIT_REGEX.test(text)) {
        e.preventDefault(); addMany(text); input.value = '';
      }
    });

    initial.forEach((v) => listEl.appendChild(buildRow(v)));
    updateCount();
  }

  // ==== 2) themed file picker ==============================================
  // <input type="file" data-file-picker="اختيار ملف" name="file"/>
  function initFilePicker(input) {
    if (input._init) return;
    input._init = true;

    const label = input.dataset.filePicker || 'اختيار ملف';
    const placeholder = input.dataset.placeholder || 'لم يتم اختيار ملف';

    const wrap = document.createElement('div');
    wrap.className = 'file-picker';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    input.classList.add('file-input-hidden');
    if (!input.id) input.id = 'fp_' + Math.random().toString(36).slice(2, 8);

    const btn = document.createElement('label');
    btn.className = 'btn primary sm';
    btn.setAttribute('for', input.id);
    btn.textContent = label;

    const name = document.createElement('span');
    name.className = 'file-name';
    name.textContent = placeholder;

    wrap.appendChild(btn);
    wrap.appendChild(name);

    input.addEventListener('change', () => {
      name.textContent = input.files && input.files.length ? input.files[0].name : placeholder;
    });
  }

  // ==== 3) confirm modal on submit / click =================================
  // <form data-confirm="سيتم حذف كذا؟"> or <a data-confirm="..." data-confirm-title="حذف">
  function askConfirm({ title, message, okLabel, okKind }, onYes) {
    const root = getModalRoot();
    root.innerHTML =
      '<div class="modal-backdrop">' +
        '<div class="modal" style="max-width:460px">' +
          '<h3>' + (title || 'تأكيد') + '</h3>' +
          '<p>' + (message || 'هل أنت متأكد؟') + '</p>' +
          '<div class="controls mt">' +
            '<button class="btn sm" type="button" data-close>إلغاء</button>' +
            '<button class="btn ' + (okKind || 'danger') + ' sm" type="button" data-ok>' + (okLabel || 'تأكيد') + '</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    root.querySelector('[data-close]').addEventListener('click', closeModal);
    root.querySelector('[data-ok]').addEventListener('click', () => {
      closeModal(); onYes();
    });
  }
  window.SmartConfirm = askConfirm;

  // In-app replacements for browser alert() / prompt() so no confirmation
  // dialogs use native browser chrome. Both return Promises so callers can
  // await user input without blocking on the (removed) native modals.
  function askAlert(message, opts) {
    opts = opts || {};
    return new Promise((resolve) => {
      const root = getModalRoot();
      root.innerHTML =
        '<div class="modal-backdrop">' +
          '<div class="modal" style="max-width:460px">' +
            '<h3>' + escapeText(opts.title || 'تنبيه') + '</h3>' +
            '<p>' + escapeText(message || '') + '</p>' +
            '<div class="controls mt">' +
              '<button class="btn primary sm" type="button" data-ok>' + escapeText(opts.okLabel || 'حسناً') + '</button>' +
            '</div>' +
          '</div>' +
        '</div>';
      const done = () => { closeModal(); resolve(); };
      root.querySelector('[data-ok]').addEventListener('click', done);
    });
  }
  window.SmartAlert = askAlert;

  function askPrompt(message, opts) {
    opts = opts || {};
    return new Promise((resolve) => {
      const root = getModalRoot();
      root.innerHTML =
        '<div class="modal-backdrop">' +
          '<div class="modal" style="max-width:460px">' +
            '<h3>' + escapeText(opts.title || 'إدخال') + '</h3>' +
            '<p>' + escapeText(message || '') + '</p>' +
            '<input type="text" class="mt" style="width:100%" data-input value="' + escapeAttr(opts.defaultValue || '') + '"/>' +
            '<div class="controls mt">' +
              '<button class="btn sm" type="button" data-close>إلغاء</button>' +
              '<button class="btn primary sm" type="button" data-ok>' + escapeText(opts.okLabel || 'حفظ') + '</button>' +
            '</div>' +
          '</div>' +
        '</div>';
      const input = root.querySelector('[data-input]');
      const cancel = () => { closeModal(); resolve(null); };
      const confirm = () => {
        const val = input ? input.value : '';
        closeModal();
        resolve(val);
      };
      root.querySelector('[data-close]').addEventListener('click', cancel);
      root.querySelector('[data-ok]').addEventListener('click', confirm);
      if (input) {
        input.addEventListener('keydown', (ev) => {
          if (ev.key === 'Enter') { ev.preventDefault(); confirm(); }
          else if (ev.key === 'Escape') { ev.preventDefault(); cancel(); }
        });
        setTimeout(() => input.focus(), 0);
      }
    });
  }
  window.SmartPrompt = askPrompt;

  function escapeText(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function escapeAttr(s) {
    return escapeText(s).replace(/"/g, '&quot;');
  }

  function initConfirmForm(form) {
    if (form._init) return; form._init = true;
    form.addEventListener('submit', (e) => {
      if (form.dataset.confirmed === '1') return;
      e.preventDefault();
      askConfirm({
        title: form.dataset.confirmTitle || 'تأكيد',
        message: form.dataset.confirm,
        okLabel: form.dataset.confirmOk || 'تأكيد',
        okKind: form.dataset.confirmKind || 'danger',
      }, () => { form.dataset.confirmed = '1'; form.submit(); });
    });
  }
  function initConfirmLink(a) {
    if (a._init) return; a._init = true;
    a.addEventListener('click', (e) => {
      if (a.dataset.confirmed === '1') return;
      e.preventDefault();
      askConfirm({
        title: a.dataset.confirmTitle || 'تأكيد',
        message: a.dataset.confirm,
        okLabel: a.dataset.confirmOk || 'متابعة',
        okKind: a.dataset.confirmKind || 'primary',
      }, () => { a.dataset.confirmed = '1'; a.click(); });
    });
  }

  // ==== 4) live table filter ==============================================
  // <input data-filter="#tableId" placeholder="بحث..."/>
  function initFilter(input) {
    if (input._init) return; input._init = true;
    const target = document.querySelector(input.dataset.filter);
    if (!target) return;

    const countEl = document.createElement('span');
    countEl.className = 'filter-count';
    input.after(countEl);

    function apply() {
      const q = keyOf(input.value);
      let visible = 0, total = 0;
      target.querySelectorAll('tbody tr, tr:not(:first-child), li, .filterable').forEach((row) => {
        if (row.tagName === 'TR' && row.querySelector('th')) return;
        total += 1;
        const text = keyOf(row.textContent);
        const hit = !q || text.indexOf(q) !== -1;
        row.style.display = hit ? '' : 'none';
        if (hit) visible += 1;
      });
      countEl.textContent = q ? '(' + visible + '/' + total + ')' : '(' + total + ')';
    }
    input.addEventListener('input', apply);
    apply();
  }

  // ==== 5) password reveal ================================================
  function initReveal(input) {
    if (input._init) return; input._init = true;
    const wrap = document.createElement('div');
    wrap.className = 'password-wrap';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'password-reveal';
    btn.setAttribute('aria-label', 'إظهار / إخفاء');
    btn.textContent = '👁';
    wrap.appendChild(btn);
    btn.addEventListener('click', () => {
      const showing = input.type === 'text';
      input.type = showing ? 'password' : 'text';
      btn.classList.toggle('on', !showing);
    });
  }

  // ==== boot ==============================================================
  function boot(root) {
    (root || document).querySelectorAll('[data-tag-adder]').forEach(initTagAdder);
    (root || document).querySelectorAll('input[type=file][data-file-picker]').forEach(initFilePicker);
    (root || document).querySelectorAll('form[data-confirm]').forEach(initConfirmForm);
    (root || document).querySelectorAll('a[data-confirm]').forEach(initConfirmLink);
    (root || document).querySelectorAll('input[data-filter]').forEach(initFilter);
    (root || document).querySelectorAll('input[data-reveal-password]').forEach(initReveal);
  }
  window.SmartForms = { boot, askConfirm, askAlert, askPrompt, closeModal, normalize, keyOf };
  document.addEventListener('DOMContentLoaded', () => boot());
})();
