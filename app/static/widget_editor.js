document.querySelectorAll('[data-widget-tray]').forEach((tray) => {
  const list = tray.querySelector('[data-widget-list]');
  const field = tray.querySelector('[data-widgets-json]');
  const type = tray.querySelector('[data-widget-type]');
  const widgetId = tray.querySelector('[data-widget-id]');
  const error = tray.querySelector('[data-widget-error]');
  const entries = () => [...list.children].map((row) => JSON.parse(row.dataset.widget));
  const sync = () => { field.value = JSON.stringify(entries()); };
  const showError = (message) => { error.textContent = message; error.hidden = false; };
  const addRow = (entry) => {
    const row = document.createElement('li'); row.className = 'widget-row'; row.dataset.widget = JSON.stringify(entry);
    row.innerHTML = `<span class="widget-label"></span><span class="widget-id"></span><span class="widget-source"></span><button type="button" class="widget-remove danger" data-widget-remove aria-label="Remove this widget">✕</button>`;
    row.querySelector('.widget-label').textContent = entry.type.charAt(0).toUpperCase() + entry.type.slice(1);
    row.querySelector('.widget-id').textContent = entry.id;
    row.querySelector('.widget-source').textContent = entry.config.source || 'Source created when saved';
    list.append(row); sync();
  };
  tray.querySelector('[data-widget-add]').addEventListener('click', () => {
    error.hidden = true;
    const id = widgetId.value.trim();
    if (!id) { showError('Enter a Widget ID so this widget and its source file are easy to identify.'); return; }
    if (entries().some((entry) => entry.id === id)) { showError('Widget IDs must be unique on this page.'); return; }
    addRow({ id, type: type.value, config: {} });
    widgetId.value = '';
  });
  list.addEventListener('click', (event) => {
    const button = event.target.closest('[data-widget-remove]');
    if (!button) return;
    button.closest('.widget-row').remove(); sync();
  });
  sync();
});
