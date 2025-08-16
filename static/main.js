document.addEventListener('DOMContentLoaded', () => {
  const socket = io();
  const body = document.body;
  const currentUserId = body.dataset.currentUserId ? parseInt(body.dataset.currentUserId, 10) : null;
  const notifUrl = body.dataset.notifUrl;
  const notifLabel = body.dataset.notifLabel;

  socket.on('new_post', data => {
    const list = document.getElementById('post-list');
    if (list) {
      const item = document.createElement('li');
      const link = document.createElement('a');
      link.href = "/docs/" + data.language + "/" + data.path;
      link.textContent = data.title;
      item.appendChild(link);
      list.prepend(item);
    }
  });

  socket.on('new_notification', data => {
    if (currentUserId && data.user_id === currentUserId) {
      const link = document.querySelector(`a[href="${notifUrl}"]`);
      if (link) {
        const match = link.textContent.match(/\((\d+)\)/);
        let count = match ? parseInt(match[1], 10) + 1 : 1;
        link.textContent = `${notifLabel} (${count})`;
      }
    }
  });

  document.addEventListener('click', function (e) {
    const anchor = e.target.closest('a');
    if (!anchor) return;
    const url = anchor.href;
    if (!url.startsWith('http') || anchor.host === window.location.host) return;
    e.preventDefault();
    fetch(`/og?url=${encodeURIComponent(url)}`)
      .then(r => r.json())
      .then(data => {
        document.getElementById('ogTitle').textContent = data.title || url;
        document.getElementById('ogDescription').textContent = data.description || '';
        const img = document.getElementById('ogImage');
        if (data.image) {
          img.src = data.image;
          img.style.display = 'block';
        } else {
          img.style.display = 'none';
        }
        const cont = document.getElementById('ogContinue');
        cont.onclick = () => { window.location.href = url; };
        cont.href = url;
        const modal = new bootstrap.Modal(document.getElementById('ogModal'));
        modal.show();
      })
      .catch(() => { window.location.href = url; });
  });
});
