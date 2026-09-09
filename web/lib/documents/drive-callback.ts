let capturedDriveCallback: string | null | undefined;

function driveParam(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return new URLSearchParams(window.location.search).get("drive");
}

export function peekDriveCallback(): string | null {
  return driveParam() || capturedDriveCallback || null;
}

export function captureDriveCallback(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  const params = new URLSearchParams(window.location.search);
  const drive = params.get("drive");
  if (drive !== null) {
    params.delete("drive");
    const query = params.toString();
    const next = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
    window.history.replaceState(null, "", next);
    if (drive) {
      capturedDriveCallback = drive;
      return drive;
    }
  }
  return capturedDriveCallback || null;
}

export function consumeDriveCallback(): void {
  capturedDriveCallback = null;
}
