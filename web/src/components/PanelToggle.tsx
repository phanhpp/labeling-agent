import { useEffect, useRef } from "react";

// Hide and show a side panel the way Cursor and Claude do: a sidebar icon that stays in the same
// place, a tooltip with its shortcut, and the shortcut itself (⌘B the filters, ⌥⌘B the workspace).

const MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

export type Panel = "filters" | "workspace";
export const SHORTCUT: Record<Panel, string> = {
  filters: MAC ? "⌘B" : "Ctrl+B",
  workspace: MAC ? "⌥⌘B" : "Ctrl+Alt+B",
};

// e.code, not e.key: with ⌥ held, a Mac types "∫" for B.
const pressed = (panel: Panel, e: KeyboardEvent) =>
  (e.metaKey || e.ctrlKey) && !e.shiftKey && e.code === "KeyB" && e.altKey === (panel === "workspace");

// A window with its sidebar on the left or the right.
export function SidebarIcon({ side }: { side: "left" | "right" }) {
  const x = side === "left" ? 6 : 10;
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true">
      <rect x="1.75" y="2.75" width="12.5" height="10.5" rx="2.25" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <path d={`M${x} 3v10`} stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}

export function PanelToggle(
  { panel, side, open, onToggle, dot = false }:
  { panel: Panel; side: "left" | "right"; open: boolean; onToggle: () => void; dot?: boolean },
) {
  const verb = open ? "Hide" : "Show";
  return (
    <button
      className={`icon tip tip-${side === "left" ? "start" : "end"} ${dot ? "has-dot" : ""}`}
      aria-label={`${verb} the ${panel}`}
      aria-expanded={open}
      data-tip={`${verb} ${panel}   ${SHORTCUT[panel]}`}
      onClick={onToggle}
    >
      <SidebarIcon side={side} />
    </button>
  );
}

// The panel's keyboard shortcut, while the component that owns the panel is on screen.
export function usePanelShortcut(panel: Panel, toggle: () => void) {
  const latest = useRef(toggle);
  latest.current = toggle;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!pressed(panel, e)) return;
      e.preventDefault();
      latest.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [panel]);
}
