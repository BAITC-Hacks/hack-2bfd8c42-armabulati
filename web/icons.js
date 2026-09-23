'use strict';

function icon(name) {
  // All icon identifiers are static application-owned names.
  return `<svg class="icon" aria-hidden="true" focusable="false"><use href="/icons.svg#${name}"></use></svg>`;
}

(() => {
  const DELAY = 1500;
  let timer, anchor, keyboard = false;
  const tooltip = document.createElement('div');
  tooltip.id = 'icon-tooltip';
  tooltip.className = 'icon-tooltip';
  tooltip.setAttribute('role', 'tooltip');
  tooltip.setAttribute('popover', 'manual');
  tooltip.hidden = true;
  document.body.append(tooltip);

  function hide() {
    clearTimeout(timer);
    if (anchor?.getAttribute('aria-describedby') === tooltip.id) anchor.removeAttribute('aria-describedby');
    if (tooltip.matches(':popover-open')) tooltip.hidePopover();
    tooltip.hidden = true;
    anchor = null;
  }

  function schedule(element) {
    if (element === anchor) return;
    hide();
    anchor = element;
    timer = setTimeout(() => {
      if (!anchor?.isConnected) return hide();
      const bounds = anchor.getBoundingClientRect();
      if (!bounds.width || !bounds.height) return hide();
      tooltip.textContent = anchor.dataset.tooltip;
      tooltip.hidden = false;
      if (tooltip.showPopover) tooltip.showPopover();
      const size = tooltip.getBoundingClientRect();
      const left = Math.min(Math.max(8, bounds.left + (bounds.width - size.width) / 2), innerWidth - size.width - 8);
      const below = bounds.bottom + 9;
      const top = below + size.height > innerHeight - 8 ? Math.max(8, bounds.top - size.height - 9) : below;
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
      anchor.setAttribute('aria-describedby', tooltip.id);
    }, DELAY);
  }

  document.addEventListener('pointerover', event => {
    if (event.pointerType === 'touch') return;
    const target = event.target.closest?.('[data-tooltip]');
    if (target) schedule(target);
  });
  document.addEventListener('pointerout', event => {
    if (anchor && !anchor.contains(event.relatedTarget)) hide();
  });
  document.addEventListener('focusin', event => {
    const target = event.target.closest?.('[data-tooltip]');
    if (keyboard && target) schedule(target);
  });
  document.addEventListener('focusout', hide);
  document.addEventListener('pointerdown', () => {keyboard = false; hide()});
  document.addEventListener('keydown', event => {
    if (event.key === 'Tab') keyboard = true;
    if (event.key === 'Escape') hide();
  });
  document.addEventListener('scroll', hide, true);
  window.addEventListener('resize', hide);
})();
