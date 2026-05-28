import { Link, useRouterState } from "@tanstack/react-router";
import {
  Apple,
  CalendarDays,
  LayoutDashboard,
  type LucideIcon,
} from "lucide-react";

const TABS: { to: string; label: string; Icon: LucideIcon }[] = [
  { to: "/foods", label: "Продукты", Icon: Apple },
  { to: "/dashboard", label: "Дневник", Icon: LayoutDashboard },
  { to: "/calendar", label: "Календарь", Icon: CalendarDays },
];

export function TabBar() {
  const { location } = useRouterState();
  const pathname = location.pathname;

  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-50 flex justify-center pb-[max(env(safe-area-inset-bottom),12px)]"
      aria-label="Основная навигация"
    >
      <div className="liquid-glass flex w-auto max-w-[88vw] items-center gap-1 rounded-full px-1.5 py-1.5">
        {TABS.map(({ to, label, Icon }) => {
          const selected = pathname === to;
          return (
            <Link
              key={to}
              to={to}
              aria-label={label}
              aria-current={selected ? "page" : undefined}
              className="flex flex-col items-center gap-0.5 rounded-full px-3 py-1 transition active:scale-95"
              style={{
                color: selected ? "var(--accent)" : "var(--tg-hint)",
                background: selected ? "var(--accent-soft)" : "transparent",
              }}
            >
              <Icon
                size={20}
                strokeWidth={selected ? 2.4 : 2}
                aria-hidden="true"
              />
              <span
                className="text-[11px] font-medium"
                style={{ opacity: selected ? 1 : 0.85 }}
              >
                {label}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
