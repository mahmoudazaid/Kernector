import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MessageFeedbackControls } from "@/components/chat/MessageFeedbackControls";
import { ApiError } from "@/lib/api/errors";

const upsertResponseFeedback = vi.fn();
const clearResponseFeedback = vi.fn();
const getResponseFeedback = vi.fn();

vi.mock("@/lib/api/feedback", () => ({
  upsertResponseFeedback: (...args: unknown[]) => upsertResponseFeedback(...args),
  clearResponseFeedback: (...args: unknown[]) => clearResponseFeedback(...args),
  getResponseFeedback: (...args: unknown[]) => getResponseFeedback(...args),
}));

describe("MessageFeedbackControls", () => {
  beforeEach(() => {
    upsertResponseFeedback.mockReset();
    clearResponseFeedback.mockReset();
    getResponseFeedback.mockReset();
    getResponseFeedback.mockRejectedValue(
      new ApiError({
        status: 404,
        title: "Feedback not found",
        detail: "No feedback found for this response.",
        code: "feedback_not_found",
      }),
    );
  });

  it("submits positive rating and shows success", async () => {
    const user = userEvent.setup();
    const onRatingChange = vi.fn();
    upsertResponseFeedback.mockResolvedValue({
      request_id: "req-1",
      rating: "positive",
    });
    render(
      <MessageFeedbackControls
        baseUrl="http://127.0.0.1:8000"
        requestId="req-1"
        conversationId="conv-1"
        clientMessageId="a-1"
        onRatingChange={onRatingChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Thumbs up" }));

    await waitFor(() => {
      expect(upsertResponseFeedback).toHaveBeenCalledWith({
        baseUrl: "http://127.0.0.1:8000",
        requestId: "req-1",
        conversationId: "conv-1",
        clientMessageId: "a-1",
        body: { rating: "positive" },
      });
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Thanks for the feedback.",
    );
    expect(screen.getByRole("button", { name: "Thumbs up" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(onRatingChange).toHaveBeenCalledWith("positive");
  });

  it("hydrates selected rating from the server without thanks copy", async () => {
    getResponseFeedback.mockResolvedValue({
      request_id: "req-1",
      rating: "negative",
    });
    const onRatingChange = vi.fn();
    render(
      <MessageFeedbackControls
        baseUrl="http://127.0.0.1:8000"
        requestId="req-1"
        conversationId="conv-1"
        clientMessageId="a-1"
        onRatingChange={onRatingChange}
      />,
    );
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Thumbs down" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
    expect(screen.queryByText("Thanks for the feedback.")).toBeNull();
    expect(onRatingChange).toHaveBeenCalledWith("negative");
  });

  it("ignores a stale hydrate response after the user saves a rating", async () => {
    let rejectHydrate!: (reason: unknown) => void;
    getResponseFeedback.mockImplementation(
      () =>
        new Promise((_, reject) => {
          rejectHydrate = reject;
        }),
    );
    upsertResponseFeedback.mockResolvedValue({
      request_id: "req-1",
      rating: "positive",
    });
    const onRatingChange = vi.fn();
    const user = userEvent.setup();
    render(
      <MessageFeedbackControls
        baseUrl="http://127.0.0.1:8000"
        requestId="req-1"
        conversationId="conv-1"
        clientMessageId="a-1"
        onRatingChange={onRatingChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Thumbs up" }));
    await waitFor(() => {
      expect(upsertResponseFeedback).toHaveBeenCalled();
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Thanks for the feedback.",
    );
    expect(onRatingChange).toHaveBeenCalledWith("positive");

    rejectHydrate(
      new ApiError({
        status: 404,
        title: "Feedback not found",
        detail: "No feedback found for this response.",
        code: "feedback_not_found",
      }),
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Thumbs up" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
    expect(screen.getByRole("status")).toHaveTextContent(
      "Thanks for the feedback.",
    );
    expect(onRatingChange).not.toHaveBeenCalledWith(null);
  });

  it("ignores a stale hydrate success after the user changes rating", async () => {
    let resolveHydrate!: (value: unknown) => void;
    getResponseFeedback.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveHydrate = resolve;
        }),
    );
    upsertResponseFeedback.mockResolvedValue({
      request_id: "req-1",
      rating: "negative",
    });
    const onRatingChange = vi.fn();
    const user = userEvent.setup();
    render(
      <MessageFeedbackControls
        baseUrl="http://127.0.0.1:8000"
        requestId="req-1"
        conversationId="conv-1"
        clientMessageId="a-1"
        initialRating="positive"
        onRatingChange={onRatingChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Thumbs down" }));
    await waitFor(() => {
      expect(upsertResponseFeedback).toHaveBeenCalledWith(
        expect.objectContaining({ body: { rating: "negative" } }),
      );
    });
    expect(onRatingChange).toHaveBeenCalledWith("negative");

    resolveHydrate({ request_id: "req-1", rating: "positive" });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Thumbs down" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
    expect(onRatingChange).not.toHaveBeenCalledWith("positive");
  });

  it("restores initialRating from persisted message state", async () => {
    render(
      <MessageFeedbackControls
        baseUrl="http://127.0.0.1:8000"
        requestId="req-1"
        conversationId="conv-1"
        clientMessageId="a-1"
        initialRating="positive"
      />,
    );
    expect(screen.getByRole("button", { name: "Thumbs up" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.queryByText("Thanks for the feedback.")).toBeNull();
  });

  it("allows changing rating with another PUT", async () => {
    const user = userEvent.setup();
    upsertResponseFeedback.mockResolvedValue({ request_id: "req-1", rating: "positive" });
    render(
      <MessageFeedbackControls
        baseUrl="http://127.0.0.1:8000"
        requestId="req-1"
        conversationId="conv-1"
        clientMessageId="a-1"
      />,
    );
    await user.click(screen.getByRole("button", { name: "Thumbs up" }));
    await screen.findByText("Thanks for the feedback.");

    upsertResponseFeedback.mockResolvedValue({
      request_id: "req-1",
      rating: "negative",
    });
    await user.click(screen.getByRole("button", { name: "Thumbs down" }));
    await waitFor(() => {
      expect(upsertResponseFeedback).toHaveBeenLastCalledWith(
        expect.objectContaining({ body: { rating: "negative" } }),
      );
    });
    expect(screen.getByRole("button", { name: "Thumbs down" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("clears rating when the selected thumb is clicked again", async () => {
    const user = userEvent.setup();
    const onRatingChange = vi.fn();
    upsertResponseFeedback.mockResolvedValue({ request_id: "req-1", rating: "positive" });
    clearResponseFeedback.mockResolvedValue(undefined);
    render(
      <MessageFeedbackControls
        baseUrl="http://127.0.0.1:8000"
        requestId="req-1"
        conversationId={null}
        clientMessageId="a-1"
        onRatingChange={onRatingChange}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Thumbs up" }));
    expect(await screen.findByRole("button", { name: "Thumbs up" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: "Thumbs up" }));
    await waitFor(() => {
      expect(clearResponseFeedback).toHaveBeenCalledWith({
        baseUrl: "http://127.0.0.1:8000",
        requestId: "req-1",
      });
    });
    expect(screen.getByRole("button", { name: "Thumbs up" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(onRatingChange).toHaveBeenCalledWith(null);
  });

  it("treats clear 404 as success when the server has no feedback row", async () => {
    const user = userEvent.setup();
    const onRatingChange = vi.fn();
    clearResponseFeedback.mockRejectedValue(
      new ApiError({
        status: 404,
        title: "Feedback not found",
        detail: "No feedback found for this response.",
        code: "feedback_not_found",
      }),
    );
    render(
      <MessageFeedbackControls
        baseUrl="http://127.0.0.1:8000"
        requestId="req-1"
        conversationId="conv-1"
        clientMessageId="a-1"
        initialRating="positive"
        onRatingChange={onRatingChange}
      />,
    );
    expect(screen.getByRole("button", { name: "Thumbs up" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: "Thumbs up" }));
    await waitFor(() => {
      expect(clearResponseFeedback).toHaveBeenCalled();
    });
    expect(screen.getByRole("button", { name: "Thumbs up" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(onRatingChange).toHaveBeenCalledWith(null);
  });

  it("shows recoverable error and retry", async () => {
    const user = userEvent.setup();
    upsertResponseFeedback.mockRejectedValue(
      new ApiError({
        status: 500,
        title: "Operational error",
        detail: "Could not save feedback.",
        code: "operational_error",
      }),
    );
    render(
      <MessageFeedbackControls
        baseUrl="http://127.0.0.1:8000"
        requestId="req-1"
        conversationId="conv-1"
        clientMessageId="a-1"
      />,
    );
    await user.click(screen.getByRole("button", { name: "Thumbs up" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not save feedback.",
    );
    upsertResponseFeedback.mockResolvedValue({
      request_id: "req-1",
      rating: "positive",
    });
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(upsertResponseFeedback).toHaveBeenCalledTimes(2);
    });
  });
});
