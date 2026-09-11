import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { DocumentViewer } from "@/components/documents/DocumentViewer";

const createObjectURL = URL.createObjectURL as Mock;
const revokeObjectURL = URL.revokeObjectURL as Mock;

afterEach(() => {
  vi.clearAllMocks();
});

describe("DocumentViewer", () => {
  it("renders PDF previews in a sandboxed iframe without trusting response content type", async () => {
    createObjectURL.mockReturnValue("blob:pdf-preview");
    const getContent = vi.fn().mockResolvedValue({
      blob: new Blob(["%PDF"], { type: "text/html" }),
      contentType: "text/html",
      fileName: "wrong.html",
    });

    render(
      <DocumentViewer
        sourceId="src-1"
        fileName="spec.pdf"
        contentFormat="pdf"
        baseUrl="http://api.test"
        getContent={getContent}
        onError={vi.fn()}
      />,
    );

    const iframe = await screen.findByTitle("Preview of spec.pdf");
    expect(iframe).toHaveAttribute("src", "blob:pdf-preview");
    expect(iframe).toHaveAttribute("sandbox", "allow-scripts");
    expect(iframe.getAttribute("sandbox")).not.toContain("allow-same-origin");
    expect(getContent).toHaveBeenCalledWith(
      expect.objectContaining({
        baseUrl: "http://api.test",
        sourceId: "src-1",
        signal: expect.any(AbortSignal),
      }),
    );
  });

  it("renders text as text content", async () => {
    render(
      <DocumentViewer
        sourceId="src-1"
        fileName="spec.md"
        contentFormat="markdown"
        baseUrl="http://api.test"
        getContent={vi.fn().mockResolvedValue({
          blob: new Blob(["<strong>plain</strong>"]),
          contentType: "text/html",
          fileName: null,
        })}
        onError={vi.fn()}
      />,
    );

    expect(await screen.findByText("<strong>plain</strong>")).toBeInTheDocument();
    expect(document.querySelector("strong")).toBeNull();
  });

  it("revokes preview object URLs on source change and unmount", async () => {
    createObjectURL
      .mockReturnValueOnce("blob:first-preview")
      .mockReturnValueOnce("blob:second-preview");
    const getContent = vi.fn().mockResolvedValue({
      blob: new Blob(["%PDF"]),
      contentType: "application/octet-stream",
      fileName: null,
    });
    const props = {
      fileName: "spec.pdf",
      contentFormat: "pdf",
      baseUrl: "http://api.test",
      getContent,
      onError: vi.fn(),
    };

    const { rerender, unmount } = render(
      <DocumentViewer {...props} sourceId="src-1" />,
    );
    await screen.findByTitle("Preview of spec.pdf");

    rerender(<DocumentViewer {...props} sourceId="src-2" />);

    await waitFor(() => {
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:first-preview");
    });
    await screen.findByTitle("Preview of spec.pdf");

    unmount();

    expect(revokeObjectURL).toHaveBeenCalledWith("blob:second-preview");
  });
});
