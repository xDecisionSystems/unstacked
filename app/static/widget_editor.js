document.querySelectorAll('[data-widget-tray]').forEach((tray) => {
  const list = tray.querySelector('[data-widget-list]');
  const field = tray.querySelector('[data-widgets-json]');
  const type = tray.querySelector('[data-widget-type]');
  const widgetId = tray.querySelector('[data-widget-id]');
  const widgetIdError = tray.querySelector('[data-widget-id-error]');
  const error = tray.querySelector('[data-widget-error]');
  const entries = () => [...list.children].map((row) => JSON.parse(row.dataset.widget));
  const sync = () => { field.value = JSON.stringify(entries()); };
  const showError = (message) => { error.textContent = message; error.hidden = false; };
  // Mirrors app.paths.make_slug's normalization (the same function
  // widget_source_path uses to name a generated source file), not the
  // looser casefold-only comparison app.content._validate_widget_entries
  // uses for its own, more general "no two widgets share an id" rule.
  // This check exists specifically to catch the narrower case that rule
  // wouldn't: two ids that differ only in punctuation would both pass it,
  // then collide once slugified into the same filename server-side.
  const widgetKey = (value) => value.trim().toLocaleLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  const validateWidgetId = () => {
    const id = widgetId.value.trim();
    const duplicate = id && entries().some((entry) => widgetKey(entry.id) === widgetKey(id));
    widgetIdError.hidden = !duplicate;
    widgetIdError.textContent = duplicate ? 'Choose a unique Widget ID for this book or page.' : '';
    return !duplicate;
  };
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
    if (!validateWidgetId()) return;
    addRow({ id, type: type.value, config: {} });
    widgetId.value = '';
    widgetIdError.hidden = true;
  });
  widgetId.addEventListener('input', validateWidgetId);
  list.addEventListener('click', (event) => {
    const button = event.target.closest('[data-widget-remove]');
    if (!button) return;
    button.closest('.widget-row').remove(); sync();
  });
  sync();
});
