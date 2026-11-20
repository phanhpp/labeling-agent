// Drag a panel's edge. widthAt turns the pointer's x into the panel's width; set clamps and stores it.
export function dragEdge(e: React.PointerEvent, widthAt: (clientX: number) => number, set: (px: number) => void) {
  e.preventDefault();
  const handle = e.currentTarget as HTMLElement;
  const move = (ev: PointerEvent) => set(widthAt(ev.clientX));
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    document.body.classList.remove("resizing");
    handle.classList.remove("dragging");
  };
  document.body.classList.add("resizing"); // no text selection, and the resize cursor everywhere
  handle.classList.add("dragging");
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}
