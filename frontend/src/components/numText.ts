// 1.46: numeric settings fields keep the TYPED TEXT and commit a number only when the text is a complete number.
// 1.45.0 bound the <input> straight to Number(text): typing "0." stored 0, React rewrote the field to "0" and the next digit made "05" = 5 -
// fractions (risk %, costs, sigma) could not be typed and became 10x larger.

/** null = empty (not set), undefined = incomplete / invalid text (nothing is committed), number = value to store. */
export function parseNumText(t: string): number | null | undefined {
  const s = String(t ?? "").trim().replace(",", ".");
  if (s === "") return null;
  if (!/^[-+]?(\d+\.?\d*|\.\d+)$/.test(s)) return undefined;
  const n = Number(s);
  return Number.isFinite(n) ? n : undefined;
}

/** Text to show for `value`: the user's own text while it still means this value ("0." / "0,5" / "1.50"), otherwise the value itself. */
export function syncNumText(text: string, value: number | null | undefined): string {
  const cur = parseNumText(text);
  if (cur !== undefined && cur === (value ?? null)) return text;
  if (cur === undefined && text !== "" && value === undefined) return text;
  return value == null ? "" : String(value);
}
