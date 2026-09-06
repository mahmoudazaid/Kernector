import { describe, expect, it } from "vitest";
import { validateUpload } from "@/lib/documents/upload";

const constraints = {
  supported_suffixes: [".markdown", ".md", ".pdf", ".txt"],
  max_upload_bytes: 5_242_880,
};

describe("validateUpload", () => {
  it("rejects when nothing is selected", () => {
    expect(validateUpload(null, constraints)).toEqual({
      ok: false,
      message: "Choose a document to upload before submitting.",
    });
  });

  it("rejects unsupported suffixes with the Streamlit message shape", () => {
    const file = new File(["x"], "notes.docx");
    expect(validateUpload(file, constraints)).toEqual({
      ok: false,
      message:
        "unsupported document type ('.docx'); supported types are .markdown, .md, .pdf, .txt",
    });
  });

  it("rejects empty files", () => {
    const file = new File([], "empty.md");
    expect(validateUpload(file, constraints)).toEqual({
      ok: false,
      message: "Choose a document to upload before submitting.",
    });
  });

  it("rejects oversize files with the byte limit", () => {
    const file = new File([new Uint8Array(9)], "big.md");
    expect(
      validateUpload(file, {
        supported_suffixes: [".md"],
        max_upload_bytes: 8,
      }),
    ).toEqual({
      ok: false,
      message: "Upload must be at most 8 bytes.",
    });
  });

  it("accepts a valid markdown upload", () => {
    const file = new File(["# hello"], "spec.md", { type: "text/markdown" });
    expect(validateUpload(file, constraints)).toEqual({ ok: true });
  });
});
