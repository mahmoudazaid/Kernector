/** Trigger a browser file download from a Blob without navigating away. */
export function triggerBrowserDownload(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.rel = "noopener";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // Defer revoke so the browser can start the download first.
  window.setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 0);
}
