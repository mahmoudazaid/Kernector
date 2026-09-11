import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { DocumentViewer } from "@/components/documents/DocumentViewer";

const createObjectURL = URL.createObjectURL as Mock;
const revokeObjectURL = URL.revokeObjectURL as Mock;

afterEach(() => {
  vi.clearAllMocks();
});

describe("DocumentViewer", () => {
  it("does not fetch or iframe PDF content (download-only preview)", async () => {
    const getContent = vi.fn();

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

    expect(
      await screen.findByText(/pdf preview is not shown inline/i),
    ).toBeInTheDocument();
    expect(getContent).not.toHaveBeenCalled();
    expect(document.querySelector("iframe")).toBeNull();
    expect(createObjectURL).not.toHaveBeenCalled();
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

  it("reloads text preview when refreshToken changes", async () => {
    const getContent = vi
      .fn()
      .mockResolvedValueOnce({
        blob: new Blob(["v1"]),
        contentType: "text/plain",
        fileName: null,
      })
      .mockResolvedValueOnce({
        blob: new Blob(["v2"]),
        contentType: "text/plain",
        fileName: null,
      });

    const { rerender } = render(
      <DocumentViewer
        sourceId="src-1"
        fileName="spec.md"
        contentFormat="markdown"
        baseUrl="http://api.test"
        refreshToken={0}
        getContent={getContent}
        onError={vi.fn()}
      />,
    );
    expect(await screen.findByText("v1")).toBeInTheDocument();

    rerender(
      <DocumentViewer
        sourceId="src-1"
        fileName="spec.md"
        contentFormat="markdown"
        baseUrl="http://api.test"
        refreshToken={1}
        getContent={getContent}
        onError={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("v2")).toBeInTheDocument();
    });
    expect(revokeObjectURL).not.toHaveBeenCalled();
  });
});
