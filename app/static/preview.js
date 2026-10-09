const panel = document.querySelector('.artifact-preview');
if (panel) {
  const status = panel.querySelector('.preview-status');
  const image = panel.querySelector('img');
  const canvas = panel.querySelector('canvas');
  const controls = panel.querySelector('.pdf-controls');
  const previous = controls.querySelector('[data-prev]');
  const next = controls.querySelector('[data-next]');
  const label = controls.querySelector('.page-label');
  const url = panel.dataset.mediaUrl;

  async function preview() {
    if (panel.dataset.mediaType.startsWith('image/')) {
      image.onload = () => { status.textContent = ''; };
      image.onerror = () => {
        image.hidden = true;
        status.textContent = 'Image preview unavailable. You can download the artifact below.';
      };
      image.src = url;
      image.hidden = false;
      return;
    }

    const pdfjs = await import('/static/js/pdf.mjs');
    pdfjs.GlobalWorkerOptions.workerSrc = '/static/js/pdf.worker.mjs';
    const pdf = await pdfjs.getDocument({
      url, standardFontDataUrl: '/static/js/standard_fonts/', isEvalSupported: false,
    }).promise;
    let current = 1;
    let busy = false;
    let pendingResize = false;
    async function render() {
      if (busy) { pendingResize = true; return; }
      busy = true;
      previous.disabled = next.disabled = true;
      try {
        const page = await pdf.getPage(current);
        const viewport = page.getViewport({ scale: 1 });
        const width = Math.min(panel.clientWidth, 928);
        const scale = width / viewport.width;
        const density = Math.min(window.devicePixelRatio || 1, 2);
        const pixels = page.getViewport({ scale: scale * density });
        canvas.width = Math.ceil(pixels.width);
        canvas.height = Math.ceil(pixels.height);
        canvas.hidden = false;
        await page.render({ canvasContext: canvas.getContext('2d'), viewport: pixels }).promise;
        label.textContent = `${current} / ${pdf.numPages}`;
        status.textContent = '';
      } finally {
        busy = false;
        previous.disabled = current <= 1;
        next.disabled = current >= pdf.numPages;
      }
      if (pendingResize) { pendingResize = false; await render(); }
    }
    const failed = () => { status.textContent = 'PDF preview unavailable. You can download the artifact below.'; };
    previous.onclick = () => { if (!busy && current > 1) { current--; render().catch(failed); } };
    next.onclick = () => { if (!busy && current < pdf.numPages) { current++; render().catch(failed); } };
    controls.hidden = false;
    await render();
    let width = panel.clientWidth;
    new ResizeObserver(() => {
      if (panel.clientWidth !== width) {
        width = panel.clientWidth;
        render().catch(failed);
      }
    }).observe(panel);
  }
  preview().catch(() => {
    controls.hidden = true;
    canvas.hidden = true;
    status.textContent = 'Preview unavailable. You can download the artifact below.';
  });
}
