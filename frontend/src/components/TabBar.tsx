import { Tabbar } from "@telegram-apps/telegram-ui";

export type Tab = "dashboard" | "calendar" | "profile";

interface Props {
  active: Tab;
  onChange: (tab: Tab) => void;
}

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "dashboard", label: "Сегодня", icon: "📊" },
  { id: "calendar", label: "Календарь", icon: "📅" },
  { id: "profile", label: "Профиль", icon: "👤" },
];

export function TabBar({ active, onChange }: Props) {
  return (
    <Tabbar>
      {TABS.map((t) => (
        <Tabbar.Item
          key={t.id}
          text={t.label}
          selected={active === t.id}
          onClick={() => onChange(t.id)}
        >
          <span style={{ fontSize: 22, lineHeight: "28px" }}>{t.icon}</span>
        </Tabbar.Item>
      ))}
    </Tabbar>
  );
}
