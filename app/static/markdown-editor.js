(() => {
  const MILKDOWN_URL = 'https://esm.sh/@milkdown/crepe@7.21.1?bundle&target=es2020';

  async function mount(textarea, Crepe) {
    if (textarea.dataset.enhanced === 'true') return;
    const root = document.createElement('div');
    root.className = 'milkdown-host';
    textarea.before(root);

    try {
      const editor = new Crepe({
        root,
        defaultValue: textarea.value,
        features: {
          [Crepe.Feature.ImageBlock]: false,
          [Crepe.Feature.TopBar]: true,
        },
      });
      await editor.create();
      textarea.dataset.enhanced = 'true';
      textarea.hidden = true;
      textarea.closest('form').addEventListener('submit', () => {
        textarea.value = editor.getMarkdown();
      });
    } catch (error) {
      root.remove();
      console.error('Milkdown could not start; the Markdown textarea remains available.', error);
    }
  }

  async function start() {
    try {
      const { Crepe } = await import(MILKDOWN_URL);
      document.querySelectorAll('textarea[data-markdown-editor]').forEach((textarea) => {
        mount(textarea, Crepe);
      });
    } catch (error) {
      console.error('Milkdown could not load; the Markdown textarea remains available.', error);
    }
  }

  start();
})();
