for (const panel of document.querySelectorAll('[data-resolver-link]')) {
  const status = panel.querySelector('.copy-status');
  const copyLink = panel.querySelector('[data-copy-link]');
  const copyQr = panel.querySelector('[data-copy-qr]');

  copyLink.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(panel.dataset.resolverLink);
      status.textContent = 'Link copied.';
    } catch {
      status.textContent = 'Unable to copy. Select and copy the link below.';
    }
  });

  copyQr.addEventListener('click', async () => {
    copyQr.disabled = true;
    try {
      if (!navigator.clipboard?.write || !window.ClipboardItem) {
        throw new Error('Image clipboard unavailable');
      }
      // Supply the promise immediately to retain the user gesture in Safari.
      const png = fetch(panel.querySelector('img').src).then(async response => {
        if (!response.ok) throw new Error('QR image unavailable');
        return response.blob();
      });
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': png })]);
      status.textContent = 'QR code copied.';
    } catch {
      status.textContent = 'Unable to copy the image. Use Copy link or save the QR image.';
    } finally {
      copyQr.disabled = false;
    }
  });
}
