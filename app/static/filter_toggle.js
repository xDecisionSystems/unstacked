(() => {
  document.querySelectorAll('[data-filter-toggle]').forEach((button) => {
    const input = document.getElementById(button.getAttribute('aria-controls'));
    if (!input) return;
    button.addEventListener('click', () => {
      const opening = input.hidden;
      input.hidden = !opening;
      button.setAttribute('aria-expanded', String(opening));
      if (opening) input.focus();
    });
  });
})();
