// The page of the Labels list you came from: its URL (filters and page) and the label ids in order.
// The decision page uses it for "Back to the list" and "Previous / Next posting". Kept in the tab's
// session storage, so it survives a reload; a blocked storage just means no "Next".

const KEY = "label-list";

export type ListContext = { url: string; ids: number[] };

export function saveListContext(url: string, ids: number[]): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ url, ids }));
  } catch {
    /* only a convenience */
  }
}

export function readListContext(): ListContext | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as ListContext) : null;
  } catch {
    return null;
  }
}

// The previous and next label ids around this one, if it is in the remembered list.
export function neighbours(ctx: ListContext | null, id: number): { prev?: number; next?: number } {
  const i = ctx?.ids.indexOf(id) ?? -1;
  if (!ctx || i < 0) return {};
  return { prev: ctx.ids[i - 1], next: ctx.ids[i + 1] };
}
