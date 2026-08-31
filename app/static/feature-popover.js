// Wires every ".feature-grid-checkbox" rendered by the feature_popover Jinja
// macro (app/templates/_widgets.html). One checkbox change fires exactly one
// POST to /home/feature or /home/remove for that grid alone -- neither route
// accepts a multi-grid batch, so there is no "diff the whole panel" step.
// Delegated on document (not per-popover) since this file loads once from
// base.html regardless of which page's cards are on screen.
(() => {
  document.addEventListener('change', async (event) => {
    const checkbox = event.target.closest('.feature-grid-checkbox');
    if (!checkbox) return;
    const details = checkbox.closest('.feature-popover');
    if (!details) return;

    const nowChecked = checkbox.checked;
    checkbox.disabled = true;
    const body = new URLSearchParams({
      csrf_token: details.dataset.csrf || '',
      target: details.dataset.target || '',
      grid_id: checkbox.dataset.gridId || '',
      return_to: details.dataset.returnTo || '',
    });
    try {
      const response = await fetch(nowChecked ? '/home/feature' : '/home/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body,
      });
      if (!response.ok && !response.redirected) {
        throw new Error(`Request failed (${response.status})`);
      }
      const anyChecked = Array.from(
        details.querySelectorAll('.feature-grid-checkbox')
      ).some((box) => box.checked);
      const summary = details.querySelector(':scope > summary.feature-star');
      if (summary) {
        summary.classList.toggle('is-featured', anyChecked);
        const glyph = summary.querySelector('span[aria-hidden]');
        if (glyph) glyph.textContent = anyChecked ? '★' : '☆';
      }
    } catch (error) {
      checkbox.checked = !nowChecked;
      window.alert('Could not update that featured grid. Please try again.');
    } finally {
      checkbox.disabled = false;
    }
  });
})();
