import { useState, type ReactNode } from "react";
import { store, stored } from "../context";

// A workspace section that folds away, closed by default and remembered per browser. While closed,
// a short hint can say something is running, so nothing important is hidden.
export function Fold({ id, title, hint, children, testid }: { id: string; title: string; hint?: string; children: ReactNode; testid?: string }) {
  const [open, setOpen] = useState(() => stored(`fold-${id}`, "closed") === "open");
  return (
    <section data-testid={testid}>
      <details
        className="fold"
        open={open}
        onToggle={(e) => {
          const now = (e.currentTarget as HTMLDetailsElement).open;
          store(`fold-${id}`, now ? "open" : "closed");
          setOpen(now);
        }}
      >
        <summary>
          <span className="label-text">{title}</span>
          {!open && hint && <span className="fold-hint">{hint}</span>}
        </summary>
        <div className="fold-body">{children}</div>
      </details>
    </section>
  );
}
