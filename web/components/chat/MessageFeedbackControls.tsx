"use client";

import { useEffect, useRef, useState } from "react";

import {
  clearResponseFeedback,
  getResponseFeedback,
  upsertResponseFeedback,
  type FeedbackRating,
} from "@/lib/api/feedback";
import { ApiError } from "@/lib/api/errors";
import { Button } from "@/components/ui/Button";

type MessageFeedbackControlsProps = {
  baseUrl: string;
  requestId: string;
  conversationId: string | null;
  clientMessageId: string;
  initialRating?: FeedbackRating | null;
  onRatingChange?: (rating: FeedbackRating | null) => void;
};

type FeedbackStatus = "idle" | "pending" | "success" | "error";
type PendingAction = FeedbackRating | "clear";

const THUMB_UP_ICON = (
  <svg
    className="kern-chat-feedback-icon"
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
  >
    <path
      d="M8.5 10.5V19.5H6.2A1.7 1.7 0 0 1 4.5 17.8V12.2A1.7 1.7 0 0 1 6.2 10.5H8.5Z"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
    <path
      d="M8.5 19.5h7.4c1.1 0 2-.8 2.1-1.9l.7-5.2a1.8 1.8 0 0 0-1.8-2H13l.8-3.4a1.7 1.7 0 0 0-1.6-2.1h-.3L8.5 10.5"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
  </svg>
);

const THUMB_DOWN_ICON = (
  <svg
    className="kern-chat-feedback-icon"
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
  >
    <path
      d="M8.5 13.5V4.5H6.2A1.7 1.7 0 0 0 4.5 6.2v5.6A1.7 1.7 0 0 0 6.2 13.5H8.5Z"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
    <path
      d="M8.5 4.5h7.4c1.1 0 2 .8 2.1 1.9l.7 5.2a1.8 1.8 0 0 1-1.8 2H13l.8 3.4a1.7 1.7 0 0 1-1.6 2.1h-.3L8.5 13.5"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
  </svg>
);

export function MessageFeedbackControls({
  baseUrl,
  requestId,
  conversationId,
  clientMessageId,
  initialRating = null,
  onRatingChange,
}: MessageFeedbackControlsProps) {
  const [rating, setRating] = useState<FeedbackRating | null>(
    initialRating ?? null,
  );
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [status, setStatus] = useState<FeedbackStatus>(
    initialRating ? "success" : "idle",
  );
  const [error, setError] = useState<string | null>(null);
  const [userAck, setUserAck] = useState(false);
  const hydrateAbortRef = useRef<AbortController | null>(null);
  const userActedRef = useRef(false);

  const busy = status === "pending";

  useEffect(() => {
    setRating(initialRating ?? null);
    if (initialRating) {
      setStatus((current) => (current === "pending" ? current : "success"));
    }
  }, [initialRating]);

  useEffect(() => {
    userActedRef.current = false;
    const controller = new AbortController();
    hydrateAbortRef.current = controller;
    void (async () => {
      try {
        const stored = await getResponseFeedback({
          baseUrl,
          requestId,
          signal: controller.signal,
        });
        if (controller.signal.aborted || userActedRef.current) {
          return;
        }
        setRating(stored.rating);
        setStatus("success");
        onRatingChange?.(stored.rating);
      } catch (caught) {
        if (controller.signal.aborted || userActedRef.current) {
          return;
        }
        if (caught instanceof ApiError && caught.status === 404) {
          if (initialRating == null) {
            setRating(null);
            setStatus("idle");
          }
          return;
        }
        // Keep local/persisted rating on hydrate failure.
      }
    })();
    return () => {
      controller.abort();
      if (hydrateAbortRef.current === controller) {
        hydrateAbortRef.current = null;
      }
    };
    // Hydrate once per request identity; parent persistence is via onRatingChange.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional mount/requestId hydrate
  }, [baseUrl, requestId]);

  function beginUserAction() {
    userActedRef.current = true;
    hydrateAbortRef.current?.abort();
  }

  async function submit(next: FeedbackRating) {
    if (busy) {
      return;
    }
    beginUserAction();
    setPendingAction(next);
    setStatus("pending");
    setError(null);
    try {
      await upsertResponseFeedback({
        baseUrl,
        requestId,
        conversationId,
        clientMessageId,
        body: { rating: next },
      });
      setRating(next);
      setPendingAction(null);
      setUserAck(true);
      setStatus("success");
      onRatingChange?.(next);
    } catch (caught) {
      setStatus("error");
      if (caught instanceof ApiError) {
        setError(caught.detail || "Could not save feedback. Try again.");
      } else {
        setError("Could not save feedback. Try again.");
      }
    }
  }

  async function clear() {
    if (busy) {
      return;
    }
    beginUserAction();
    setPendingAction("clear");
    setStatus("pending");
    setError(null);
    try {
      await clearResponseFeedback({ baseUrl, requestId });
      setRating(null);
      setPendingAction(null);
      setUserAck(false);
      setStatus("idle");
      onRatingChange?.(null);
    } catch (caught) {
      setStatus("error");
      if (caught instanceof ApiError) {
        setError(caught.detail || "Could not clear feedback. Try again.");
      } else {
        setError("Could not clear feedback. Try again.");
      }
    }
  }

  function onThumbClick(next: FeedbackRating) {
    if (busy) {
      return;
    }
    if (rating === next) {
      void clear();
      return;
    }
    void submit(next);
  }

  function onRetry() {
    if (pendingAction === "clear") {
      void clear();
      return;
    }
    if (pendingAction === "positive" || pendingAction === "negative") {
      void submit(pendingAction);
    }
  }

  return (
    <div className="kern-chat-feedback" data-testid="message-feedback">
      <div className="kern-chat-feedback-actions">
        <Button
          type="button"
          variant="ghost"
          className={
            rating === "positive"
              ? "kern-chat-feedback-btn is-selected"
              : "kern-chat-feedback-btn"
          }
          aria-label="Thumbs up"
          aria-pressed={rating === "positive"}
          disabled={busy}
          onClick={() => {
            onThumbClick("positive");
          }}
        >
          {THUMB_UP_ICON}
        </Button>
        <Button
          type="button"
          variant="ghost"
          className={
            rating === "negative"
              ? "kern-chat-feedback-btn is-selected"
              : "kern-chat-feedback-btn"
          }
          aria-label="Thumbs down"
          aria-pressed={rating === "negative"}
          disabled={busy}
          onClick={() => {
            onThumbClick("negative");
          }}
        >
          {THUMB_DOWN_ICON}
        </Button>
      </div>
      {status === "pending" ? (
        <p className="kern-chat-feedback-status" role="status">
          Saving feedback…
        </p>
      ) : null}
      {status === "success" && rating !== null && userAck ? (
        <p className="kern-chat-feedback-status" role="status">
          Thanks for the feedback.
        </p>
      ) : null}
      {status === "error" && error ? (
        <div className="kern-chat-feedback-error" role="alert">
          <p>{error}</p>
          <Button
            type="button"
            variant="secondary"
            disabled={busy}
            onClick={onRetry}
          >
            Retry
          </Button>
        </div>
      ) : null}
    </div>
  );
}
