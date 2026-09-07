/**
 * Chat composer length feedback (#17).
 *
 * The limit is server-owned: it arrives from `GET /api/v1/settings`
 * (`max_input_length`), which composition seeds from `MAX_INPUT_LENGTH`. This
 * module deliberately holds no limit of its own — presentation must not carry
 * a parallel validation rule (#96 owns validation).
 *
 * Length is measured in Unicode code points so it matches Python `len()` on
 * the application boundary (astral characters count as one, not two).
 */

export type InputLengthFeedback = {
  /** Characters that will actually be sent, i.e. the trimmed draft. */
  length: number;
  maxInputLength: number;
  exceeded: boolean;
  counterLabel: string;
  /** Corrective action, present only when the draft is over the limit. */
  guidance: string | null;
};

export type HistoryLengthFeedback = {
  exceeded: boolean;
  /** Corrective action when any history entry exceeds the limit. */
  guidance: string | null;
};

/** Count Unicode code points (matches Python `len` on str). */
export function codePointLength(text: string): number {
  return [...text].length;
}

export function evaluateInputLength(
  draft: string,
  maxInputLength: number,
): InputLengthFeedback {
  const length = codePointLength(draft.trim());
  const exceeded = length > maxInputLength;
  return {
    length,
    maxInputLength,
    exceeded,
    counterLabel: `${length} / ${maxInputLength} characters`,
    guidance: exceeded
      ? `Message must be at most ${maxInputLength} characters; ` +
        `remove ${length - maxInputLength} to send.`
      : null,
  };
}

/**
 * Mirror the server's per-history-entry length check so a long prior answer
 * cannot brick the conversation while the draft counter looks fine.
 */
export function evaluateHistoryLength(
  history: readonly { content: string }[],
  maxInputLength: number,
): HistoryLengthFeedback {
  for (const turn of history) {
    if (codePointLength(turn.content) > maxInputLength) {
      return {
        exceeded: true,
        guidance:
          `A previous message exceeds ${maxInputLength} characters. ` +
          `Start a new chat to continue.`,
      };
    }
  }
  return { exceeded: false, guidance: null };
}
