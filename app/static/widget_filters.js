document.querySelectorAll('.data-cards-widget').forEach((widget) => {
  const buttons = widget.querySelectorAll('.data-card-filter');
  const cards = widget.querySelectorAll('[data-card-filters]');
  const empty = widget.querySelector('[data-card-empty]');
  buttons.forEach((button) => button.addEventListener('click', () => {
    const selected = button.dataset.cardFilter;
    let visible = 0;
    buttons.forEach((item) => {
      const active = item === button;
      item.classList.toggle('is-active', active);
      item.setAttribute('aria-pressed', String(active));
    });
    cards.forEach((card) => {
      const show = selected === 'all' || card.dataset.cardFilters.split(' ').includes(selected);
      card.hidden = !show;
      if (show) visible += 1;
    });
    if (empty) empty.hidden = visible !== 0;
  }));
});
