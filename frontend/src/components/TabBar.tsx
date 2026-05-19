export type Tab = "dashboard" | "profile";

interface Props {
  active: Tab;
  onChange: (tab: Tab) => void;
}

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "dashboard", label: "Дневник", icon: "📊" },
  { id: "profile", label: "Профиль", icon: "👤" },
];

export function TabBar({ active, onChange }: Props) {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-10 flex border-t border-tg-border bg-tg-card pb-[env(safe-area-inset-bottom)]">
      {TABS.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={`flex flex-1 flex-col items-center gap-0.5 py-2.5 text-xs ${
            active === t.id ? "text-tg-link" : "text-tg-hint"
          }`}
        >
          <span className="text-lg">{t.icon}</span>
          {t.label}
        </button>
      ))}
    </nav>
  );
}
