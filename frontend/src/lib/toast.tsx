/**
 * App-wide toast/snackbar via @telegram-apps/telegram-ui Snackbar.
 *
 * Usage:
 *   const toast = useToast();
 *   toast.show({ kind: "error", message: "Не удалось сохранить" });
 *
 * One Snackbar is rendered per active toast — telegram-ui handles entry/exit
 * animation. Errors stick for 5s, success/info for 3s by default.
 */

import { Snackbar } from "@telegram-apps/telegram-ui";
import { CheckCircle2, Info, TriangleAlert } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ToastKind = "info" | "error" | "success";

export interface ToastOptions {
  kind?: ToastKind;
  message: string;
  description?: string;
  durationMs?: number;
}

interface ToastItem extends Required<Omit<ToastOptions, "description">> {
  id: string;
  description?: string;
}

interface ToastApi {
  show: (opts: ToastOptions) => void;
  error: (message: string, description?: string) => void;
  success: (message: string, description?: string) => void;
  info: (message: string, description?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const DEFAULT_DURATIONS: Record<ToastKind, number> = {
  error: 5000,
  success: 3000,
  info: 3000,
};

const KIND_ICONS: Record<ToastKind, ReactNode> = {
  error: <TriangleAlert size={20} className="text-red-400" aria-hidden />,
  success: <CheckCircle2 size={20} className="text-green-400" aria-hidden />,
  info: <Info size={20} className="text-tg-link" aria-hidden />,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: string) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const show = useCallback((opts: ToastOptions) => {
    const kind = opts.kind ?? "info";
    const item: ToastItem = {
      id:
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random()}`,
      kind,
      message: opts.message,
      description: opts.description,
      durationMs: opts.durationMs ?? DEFAULT_DURATIONS[kind],
    };
    setItems((prev) => [...prev, item]);
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      show,
      error: (message, description) =>
        show({ kind: "error", message, description }),
      success: (message, description) =>
        show({ kind: "success", message, description }),
      info: (message, description) =>
        show({ kind: "info", message, description }),
    }),
    [show],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      {items.map((t) => (
        <Snackbar
          key={t.id}
          duration={t.durationMs}
          before={KIND_ICONS[t.kind]}
          description={t.description}
          onClose={() => dismiss(t.id)}
        >
          {t.message}
        </Snackbar>
      ))}
    </ToastContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used inside <ToastProvider>");
  }
  return ctx;
}
