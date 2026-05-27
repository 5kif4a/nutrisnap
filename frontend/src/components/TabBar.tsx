import {
  Apple,
  CalendarDays,
  LayoutDashboard,
  type LucideIcon,
} from "lucide-react";

export type Tab = "dashboard" | "calendar" | "foods" | "profile";

interface Props {
  active: Tab;
  onChange: (tab: Tab) => void;
}

/** Three visible tabs — "profile" is reachable via the global gear icon. */
const TABS: { id: Tab; label: string; Icon: LucideIcon }[] = [
  { id: "foods", label: "Продукты", Icon: Apple },
  { id: "dashboard", label: "Дневник", Icon: LayoutDashboard },
  { id: "calendar", label: "Календарь", Icon: CalendarDays },
];

export function TabBar({ active, onChange }: Props) {
  // Profile view stays without a highlighted pill — it's a modal-like
  // detour reached via the global gear icon, not part of the main flow.
  const effective = active === "profile" ? null : active;

  return (
    <nav
      // High z-index so the pill always floats above content, fab, and any
      // Telegram-UI components that may layer themselves over the bottom.
      className="fixed inset-x-0 bottom-0 z-50 flex justify-center pb-[max(env(safe-area-inset-bottom),12px)]"
      aria-label="Основная навигация"
    >
      <div className="liquid-glass mx-4 flex w-full max-w-sm items-center justify-around rounded-full px-2 py-2">
        {TABS.map(({ id, label, Icon }) => {
          const selected = effective === id;
          return (
            <button
              key={id}
              onClick={() => onChange(id)}
              aria-label={label}
              aria-current={selected ? "page" : undefined}
              className="flex flex-1 flex-col items-center gap-0.5 rounded-full px-3 py-1.5 transition active:scale-95"
              style={{
                color: selected ? "var(--accent)" : "var(--tg-hint)",
                background: selected ? "var(--accent-soft)" : "transparent",
              }}
            >
              <Icon
                size={22}
                strokeWidth={selected ? 2.4 : 2}
                aria-hidden="true"
              />
              <span
                className="text-[11px] font-medium"
                style={{ opacity: selected ? 1 : 0.85 }}
              >
                {label}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
