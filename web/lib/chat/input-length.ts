/**
 * Chat composer length feedback (#17).
 *
 * The limit is server-owned: it arrives from `GET /api/v1/settings`
 * (`max_input_length`), which composition seeds from `MAX_INPUT_LENGTH`. This
 * module deliberately holds no limit of its own — presentation must not carry
 * a parallel validation rule (#96 owns validation).
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

export function evaluateInputLength(
  draft: string,
  maxInputLength: number,
): InputLengthFeedback {
  const length = draft.trim().length;
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
