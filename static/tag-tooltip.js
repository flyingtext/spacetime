document.addEventListener('DOMContentLoaded', () => {
  const tooltip = document.createElement('div');
  tooltip.className = 'tag-tooltip-card';
  tooltip.style.display = 'none';
  document.body.appendChild(tooltip);
  let hideTimeout;
  let leafletPromise;

  function loadLeaflet() {
    if (leafletPromise) return leafletPromise;
    leafletPromise = new Promise(resolve => {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = 'https://unpkg.com/leaflet/dist/leaflet.css';
      document.head.appendChild(link);
      const script = document.createElement('script');
      script.src = 'https://unpkg.com/leaflet/dist/leaflet.js';
      script.onload = () => resolve();
      document.body.appendChild(script);
    });
    return leafletPromise;
  }

  function initMap(id, lat, lon) {
    const map = L.map(id, {
      zoomControl: false,
      attributionControl: false,
      dragging: false,
      scrollWheelZoom: false,
      doubleClickZoom: false,
      boxZoom: false,
      keyboard: false,
      tap: false,
    });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
    }).addTo(map);
    map.setView([lat, lon], 11);
  }

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
      .map((d, i) => {
        const mapDiv = d.lat !== undefined && d.lon !== undefined
          ? `<div class="tooltip-map" id="tooltip-map-${i}" data-lat="${d.lat}" data-lon="${d.lon}"></div>`
          : '';
        return `<div class="tag-doc">${mapDiv}<div class="tag-doc-text"><a href="${d.url}">${d.title}</a><p>${d.snippet}</p></div></div>`;
      })
      .join('');
    clearTimeout(hideTimeout);
    tooltip.style.display = 'block';
    const rect = this.getBoundingClientRect();
    let left = rect.left + window.scrollX;
    let top = rect.bottom + window.scrollY + 5;
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;

    const margin = 10;
    const tipRect = tooltip.getBoundingClientRect();
    if (tipRect.right > window.innerWidth - margin) {
      left -= tipRect.right - (window.innerWidth - margin);
    }
    if (left < margin) {
      left = margin;
    }
    if (tipRect.bottom > window.innerHeight - margin) {
      top -= tipRect.bottom - (window.innerHeight - margin);
    }
    if (top < margin) {
      top = margin;
    }
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;

    const maps = tooltip.querySelectorAll('.tooltip-map');
    if (maps.length > 0) {
      loadLeaflet().then(() => {
        maps.forEach(m => {
          const lat = parseFloat(m.dataset.lat);
          const lon = parseFloat(m.dataset.lon);
          initMap(m.id, lat, lon);
        });
      });
    }
  }

  function hideTooltip() {
    tooltip.style.display = 'none';
  }

  function scheduleHide() {
    hideTimeout = setTimeout(hideTooltip, 100);
  }

  function maybeHideTooltip(e) {
    if (!tooltip.contains(e.relatedTarget)) {
      scheduleHide();
    }
  }

  document.querySelectorAll('a.tag-link').forEach(el => {
    el.addEventListener('mouseenter', showTooltip);
    el.addEventListener('mouseout', maybeHideTooltip);
  });

  tooltip.addEventListener('mouseenter', () => clearTimeout(hideTimeout));
  tooltip.addEventListener('mouseleave', scheduleHide);
});
