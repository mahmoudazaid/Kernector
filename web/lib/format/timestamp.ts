const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

/**
 * Instrument panel timestamp: ``09 Sep 2026, 09:35 AM``.
 *
 * Local wall clock, 12-hour, English month abbreviations. Invalid input is
 * returned unchanged.
 */
export function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const day = String(date.getDate()).padStart(2, "0");
  const month = MONTHS[date.getMonth()];
  const year = date.getFullYear();
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const period = date.getHours() >= 12 ? "PM" : "AM";
  let hours = date.getHours() % 12;
  if (hours === 0) {
    hours = 12;
  }
  return `${day} ${month} ${year}, ${String(hours).padStart(2, "0")}:${minutes} ${period}`;
}
