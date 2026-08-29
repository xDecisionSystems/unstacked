/* Drag-and-drop reordering, persisted per-browser in localStorage.
 *
 * Deliberately not saved to the wiki itself: card/chapter/page order here is
 * a personal viewing preference, not shared content -- see the book
 * dashboard, book page, and chapter rows that call this. Each call targets
 * one container whose direct children matching `itemSelector` carry a
 * stable `data-key` (the slug or page path); order is stored as that key
 * list under `storageKey`.
 *
 * `handleSelector`, when given, restricts where a drag may start from (e.g.
 * a small grip icon) without preventing normal clicks elsewhere in the
 * item -- native HTML5 drag can't be scoped to a sub-element directly, so
 * this cancels `dragstart` unless it originated inside the handle.
 */
function initDragReorder(container, opts) {
  if (!container) return;
  var itemSelector = opts.itemSelector;
  var storageKey = opts.storageKey;
  var axis = opts.axis || 'y';
  var handleSelector = opts.handleSelector || null;

  function items() {
    return Array.prototype.filter.call(container.children, function (el) {
      return el.matches(itemSelector);
    });
  }

  function savedOrder() {
    try { return JSON.parse(localStorage.getItem(storageKey) || '[]'); } catch (e) { return []; }
  }

  function applySavedOrder() {
    var order = savedOrder();
    if (!order.length) return;
    items()
      .sort(function (a, b) {
        var ia = order.indexOf(a.dataset.key), ib = order.indexOf(b.dataset.key);
        if (ia === -1) ia = order.length;
        if (ib === -1) ib = order.length;
        return ia - ib;
      })
      .forEach(function (item) { container.appendChild(item); });
  }

  function persistOrder() {
    var order = items().map(function (item) { return item.dataset.key; });
    try { localStorage.setItem(storageKey, JSON.stringify(order)); } catch (e) { /* private mode etc. */ }
  }

  applySavedOrder();

  var dragging = null;
  container.addEventListener('dragstart', function (e) {
    var item = e.target.closest(itemSelector);
    if (!item || item.parentNode !== container) return;
    if (handleSelector && !e.target.closest(handleSelector)) {
      e.preventDefault();
      return;
    }
    dragging = item;
    item.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
  });
  container.addEventListener('dragover', function (e) {
    if (!dragging) return;
    e.preventDefault();
    var item = e.target.closest(itemSelector);
    if (!item || item === dragging || item.parentNode !== container) return;
    var rect = item.getBoundingClientRect();
    var before = axis === 'x'
      ? (e.clientX - rect.left) < rect.width / 2
      : (e.clientY - rect.top) < rect.height / 2;
    container.insertBefore(dragging, before ? item : item.nextSibling);
  });
  container.addEventListener('dragend', function () {
    if (dragging) dragging.classList.remove('dragging');
    dragging = null;
    persistOrder();
  });
}
