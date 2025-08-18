document.addEventListener('DOMContentLoaded', () => {
  const tooltip = document.createElement('div');
  tooltip.className = 'tag-tooltip-card';
  tooltip.style.display = 'none';
  document.body.appendChild(tooltip);

  function showTooltip() {
    const data = this.dataset.tooltip;
    if (!data) return;
    let docs;
    try {
      docs = JSON.parse(data);
    } catch (e) {
      return;
    }
    if (!Array.isArray(docs) || docs.length === 0) return;
    tooltip.innerHTML = docs
      .map(d => `<div class="tag-doc"><a href="${d.url}">${d.title}</a><p>${d.snippet}</p></div>`)
      .join('');
    tooltip.style.display = 'block';
    const rect = this.getBoundingClientRect();
    tooltip.style.left = `${rect.left + window.scrollX}px`;
    tooltip.style.top = `${rect.bottom + window.scrollY + 5}px`;
  }

  function hideTooltip() {
    tooltip.style.display = 'none';
  }

  function maybeHideTooltip(e) {
    if (!tooltip.contains(e.relatedTarget)) {
      hideTooltip();
    }
  }

  document.querySelectorAll('a.tag-link').forEach(el => {
    el.addEventListener('mouseenter', showTooltip);
    el.addEventListener('mouseout', maybeHideTooltip);
  });

  tooltip.addEventListener('mouseleave', hideTooltip);
});
