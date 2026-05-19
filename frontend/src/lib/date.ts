// All date math is done in UTC so it stays consistent regardless of the
// browser timezone and aligns with the backend (/api/* use UTC day/month bounds).

export function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Shift a YYYY-MM-DD string by ±N days. */
export function shiftDayISO(iso: string, delta: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toISOString().slice(0, 10);
}

export function humanDate(iso: string): string {
  if (iso === todayISO()) return "Сегодня";
  if (iso === shiftDayISO(todayISO(), -1)) return "Вчера";
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("ru", {
    day: "numeric",
    month: "long",
    weekday: "short",
    timeZone: "UTC",
  });
}

// ─── Month helpers (YYYY-MM) ────────────────────────────────────────────────

export function thisMonth(): string {
  return todayISO().slice(0, 7);
}

export function monthOf(iso: string): string {
  return iso.slice(0, 7);
}

/** Shift a YYYY-MM string by ±N months. */
export function shiftMonth(ym: string, delta: number): string {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

export function monthLabel(ym: string): string {
  return new Date(`${ym}-01T00:00:00Z`).toLocaleDateString("ru", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

/**
 * Monday-first grid for a month: leading `null`s pad the first week so day 1
 * lands under its weekday. Length is a multiple of 7.
 */
export function monthGrid(ym: string): (string | null)[] {
  const [y, m] = ym.split("-").map(Number);
  const first = new Date(Date.UTC(y, m - 1, 1));
  const lead = (first.getUTCDay() + 6) % 7; // 0 = Monday
  const daysInMonth = new Date(Date.UTC(y, m, 0)).getUTCDate();

  const cells: (string | null)[] = Array(lead).fill(null);
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push(`${ym}-${String(d).padStart(2, "0")}`);
  }
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}
