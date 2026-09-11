document.querySelectorAll('[data-widget-tray]').forEach((tray) => {
  const list = tray.querySelector('[data-widget-list]');
  const field = tray.querySelector('[data-widgets-json]');
  const type = tray.querySelector('[data-widget-type]');
  const source = tray.querySelector('[data-widget-source]');
  const sourceLabel = tray.querySelector('[data-widget-source-label]');
  const error = tray.querySelector('[data-widget-error]');
  const entries = () => [...list.children].map((row) => JSON.parse(row.dataset.widget));
  const sync = () => { field.value = JSON.stringify(entries()); };
  const showError = (message) => { error.textContent = message; error.hidden = false; };
  const addRow = (entry) => {
    const row = document.createElement('li'); row.className = 'widget-row'; row.dataset.widget = JSON.stringify(entry);
    row.innerHTML = `<span class="widget-label"></span><span class="widget-id"></span><button type="button" class="widget-remove danger" data-widget-remove aria-label="Remove this widget">✕</button>`;
    row.querySelector('.widget-label').textContent = entry.type.charAt(0).toUpperCase() + entry.type.slice(1);
    row.querySelector('.widget-id').textContent = entry.config.source;
    list.append(row); sync();
  };
  tray.querySelector('[data-widget-add]').addEventListener('click', () => {
    const path = source.value.trim();
    if (type.value !== 'horizontal-rule' && !/^[a-zA-Z0-9_/-]+\.md$/.test(path)) { showError('Enter a Markdown page path, such as research/about.md.'); return; }
    error.hidden = true;
    const id = `${type.value}-${Date.now().toString(36)}`;
    addRow({ id, type: type.value, config: type.value === 'horizontal-rule' ? {} : { source: path } }); source.value = '';
  });
  type.addEventListener('change', () => { sourceLabel.hidden = type.value === 'horizontal-rule'; });
  list.addEventListener('click', (event) => {
    const button = event.target.closest('[data-widget-remove]');
    if (!button) return;
    button.closest('.widget-row').remove(); sync();
  });
  sync();
});
