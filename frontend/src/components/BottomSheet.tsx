import { X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

/* ───────── Reusable bottom sheet with drag-to-dismiss + backdrop fade.
   Extracted from FormulaSheet in pages/Profile.tsx — same animation tokens
   from index.css (animate-sheet-slide / -out, animate-sheet-fade / -out). */

interface Props {
  open: boolean;
  onClose: () => void;
  title?: string;
  /** When false, hides the X-button (used for sheets that must run to
   * completion via a different action, like the meal-type picker). */
  showCloseButton?: boolean;
  /** When true, blocks dismiss-on-backdrop-tap and drag-down. */
  blocking?: boolean;
  children: ReactNode;
}

export function BottomSheet({
  open,
  onClose,
  title,
  showCloseButton = true,
  blocking = false,
  children,
}: Props) {
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const drag = useRef<{
    startY: number;
    startT: number;
    active: boolean;
  } | null>(null);
  const [closing, setClosing] = useState(false);
  const offsetRef = useRef(0);

  useEffect(() => {
    if (!open) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !blocking) close();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, blocking]);

  // Reset internal closing/offset state whenever the sheet is reopened.
  useEffect(() => {
    if (open) {
      setClosing(false);
      offsetRef.current = 0;
      if (sheetRef.current) sheetRef.current.style.transform = "";
    }
  }, [open]);

  if (!open) return null;

  const applyOffset = (y: number) => {
    offsetRef.current = y;
    if (sheetRef.current) {
      sheetRef.current.style.transform = `translateY(${y}px)`;
    }
  };

  const close = () => {
    if (blocking) return;
    setClosing(true);
    window.setTimeout(onClose, 200);
  };

  const onDragStart = (e: React.PointerEvent<HTMLDivElement>) => {
    if (blocking) return;
    drag.current = {
      startY: e.clientY,
      startT: performance.now(),
      active: true,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
    if (sheetRef.current) sheetRef.current.style.transition = "none";
  };

  const onDragMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current?.active) return;
    const dy = e.clientY - drag.current.startY;
    applyOffset(Math.max(0, dy));
  };

  const onDragEnd = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current?.active) return;
    const dy = offsetRef.current;
    const dt = performance.now() - drag.current.startT;
    const velocity = dy / Math.max(dt, 1);
    drag.current.active = false;
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      /* pointer already gone */
    }
    if (dy > 120 || velocity > 0.6) {
      close();
      return;
    }
    if (sheetRef.current) {
      sheetRef.current.style.transition =
        "transform 220ms cubic-bezier(0.32, 0.72, 0.24, 1)";
    }
    applyOffset(0);
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-end justify-center">
      <button
        type="button"
        onClick={close}
        aria-label="Закрыть"
        disabled={blocking}
        className={`absolute inset-0 bg-black/60 backdrop-blur-sm ${
          closing ? "animate-sheet-fade-out" : "animate-sheet-fade"
        }`}
      />

      <div
        ref={sheetRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`liquid-glass relative flex max-h-[85vh] w-full max-w-md flex-col rounded-t-3xl pt-3 ${
          closing ? "animate-sheet-slide-out" : "animate-sheet-slide"
        }`}
        style={{ marginTop: "max(env(safe-area-inset-top), 24px)" }}
      >
        <div
          className="px-5"
          style={{
            touchAction: blocking ? "auto" : "none",
            cursor: blocking ? "default" : "grab",
          }}
          onPointerDown={onDragStart}
          onPointerMove={onDragMove}
          onPointerUp={onDragEnd}
          onPointerCancel={onDragEnd}
        >
          <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-white/30" />
          {(title || showCloseButton) && (
            <div className="mb-3 flex items-center justify-between">
              {title ? (
                <h2 className="text-lg font-semibold text-tg-text">{title}</h2>
              ) : (
                <span />
              )}
              {showCloseButton && !blocking && (
                <button
                  onClick={close}
                  aria-label="Закрыть"
                  className="flex h-8 w-8 items-center justify-center rounded-full bg-white/5 text-tg-hint transition active:scale-90"
                  style={{ touchAction: "auto" }}
                >
                  <X size={18} />
                </button>
              )}
            </div>
          )}
        </div>

        <div
          className="flex-1 overflow-y-auto px-5 pb-[calc(env(safe-area-inset-bottom)+24px)]"
          style={{ WebkitOverflowScrolling: "touch" }}
        >
          {children}
        </div>
      </div>
    </div>
  );
}
