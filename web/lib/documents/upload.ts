export type UploadConstraints = {
  supported_suffixes: readonly string[];
  max_upload_bytes: number;
};

export type UploadValidationResult =
  | { ok: true }
  | { ok: false; message: string };

/**
 * Client-side pre-flight for document uploads (UX only; server re-validates).
 *
 * Messages are fixed literals matching Streamlit ``_validate_upload`` semantics.
 */
export function validateUpload(
  file: File | null | undefined,
  constraints: UploadConstraints,
): UploadValidationResult {
  if (!file) {
    return {
      ok: false,
      message: "Choose a document to upload before submitting.",
    };
  }

  const name = file.name;
  const dot = name.lastIndexOf(".");
  const suffix = dot >= 0 ? name.slice(dot).toLowerCase() : "";
  if (!constraints.supported_suffixes.includes(suffix)) {
    const listed = [...constraints.supported_suffixes].sort().join(", ");
    return {
      ok: false,
      message: `unsupported document type ('${suffix}'); supported types are ${listed}`,
    };
  }

  if (file.size === 0) {
    return {
      ok: false,
      message: "Choose a document to upload before submitting.",
    };
  }

  if (file.size > constraints.max_upload_bytes) {
    return {
      ok: false,
      message: `Upload must be at most ${constraints.max_upload_bytes} bytes.`,
    };
  }

  return { ok: true };
}
