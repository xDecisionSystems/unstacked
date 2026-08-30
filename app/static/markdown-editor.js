(() => {
  function insert(textarea, before, after = '', placeholder = '') {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const selected = textarea.value.slice(start, end) || placeholder;
    textarea.setRangeText(before + selected + after, start, end, 'select');
    textarea.focus();
  }

  function prefixLines(textarea, prefix) {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const lineStart = textarea.value.lastIndexOf('\n', start - 1) + 1;
    const lineEnd = textarea.value.indexOf('\n', end);
    const stop = lineEnd === -1 ? textarea.value.length : lineEnd;
    const lines = textarea.value.slice(lineStart, stop).split('\n');
    textarea.setRangeText(lines.map((line) => prefix + line).join('\n'), lineStart, stop, 'select');
    textarea.focus();
  }

  function setHeading(textarea, level) {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const lineStart = textarea.value.lastIndexOf('\n', start - 1) + 1;
    const lineEnd = textarea.value.indexOf('\n', end);
    const stop = lineEnd === -1 ? textarea.value.length : lineEnd;
    const prefix = level ? '#'.repeat(Number(level)) + ' ' : '';
    const lines = textarea.value.slice(lineStart, stop).split('\n');
    textarea.setRangeText(
      lines.map((line) => prefix + line.replace(/^#{1,6}\s+/, '')).join('\n'),
      lineStart,
      stop,
      'select',
    );
    textarea.focus();
  }

  function button(label, command, help) {
    const element = document.createElement('button');
    element.type = 'button';
    element.className = 'markdown-tool';
    element.dataset.command = command;
    element.textContent = label;
    element.title = help;
    element.setAttribute('aria-label', help);
    return element;
  }

  function createToolbar(textarea) {
    const toolbar = document.createElement('div');
    toolbar.className = 'markdown-toolbar';
    toolbar.setAttribute('role', 'toolbar');
    toolbar.setAttribute('aria-label', 'Markdown formatting');
    const heading = document.createElement('select');
    heading.className = 'markdown-heading';
    heading.setAttribute('aria-label', 'Text style');
    [['', 'Paragraph'], ['1', 'Heading 1'], ['2', 'Heading 2'], ['3', 'Heading 3'], ['4', 'Heading 4'], ['5', 'Heading 5'], ['6', 'Heading 6']]
      .forEach(([value, label]) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        heading.append(option);
      });
    heading.addEventListener('change', () => {
      setHeading(textarea, heading.value);
      heading.value = '';
    });
    toolbar.append(heading);
    [
      ['B', 'bold', 'Bold'], ['I', 'italic', 'Italic'], ['S', 'strike', 'Strikethrough'],
      ['Quote', 'quote', 'Block quote'], ['• List', 'bullets', 'Bulleted list'],
      ['1. List', 'numbers', 'Numbered list'], ['☐ Task', 'task', 'Task list'],
      ['Link', 'link', 'Insert link'], ['Image', 'image', 'Insert image'], ['Code', 'code', 'Inline code'],
    ].forEach(([label, command, help]) => toolbar.append(button(label, command, help)));
    toolbar.addEventListener('click', (event) => {
      const target = event.target.closest('button');
      const command = target ? target.dataset.command : null;
      if (!command) return;
      if (command === 'bold') insert(textarea, '**', '**', 'bold text');
      if (command === 'italic') insert(textarea, '*', '*', 'italic text');
      if (command === 'strike') insert(textarea, '~~', '~~', 'struck text');
      if (command === 'quote') prefixLines(textarea, '> ');
      if (command === 'bullets') prefixLines(textarea, '- ');
      if (command === 'numbers') prefixLines(textarea, '1. ');
      if (command === 'task') prefixLines(textarea, '- [ ] ');
      if (command === 'link') insert(textarea, '[', '](https://)', 'link text');
      if (command === 'image') insert(textarea, '![', '](https://)', 'image description');
      if (command === 'code') insert(textarea, '`', '`', 'code');
    });
    return toolbar;
  }

  function mount(textarea) {
    if (textarea.dataset.enhanced === 'true') return;
    textarea.dataset.enhanced = 'true';
    const container = document.createElement('div');
    container.className = 'markdown-editor-container';
    textarea.before(container);
    container.append(createToolbar(textarea), textarea);
  }

  document.querySelectorAll('textarea[data-markdown-editor]').forEach(mount);
})();
