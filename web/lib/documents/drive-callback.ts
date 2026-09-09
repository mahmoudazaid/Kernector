let capturedDriveCallback: string | null | undefined;

export function readDriveCallback(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  const params = new URLSearchParams(window.location.search);
  const drive = params.get("drive");
  if (drive) {
    params.delete("drive");
    const query = params.toString();
    const next = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
    window.history.replaceState(null, "", next);
    capturedDriveCallback = drive;
    return drive;
  }
  return capturedDriveCallback ?? null;
}

export function consumeDriveCallback(): void {
  capturedDriveCallback = null;
}
