import { Tabbar } from "@telegram-apps/telegram-ui";
import {
  CalendarDays,
  LayoutDashboard,
  User,
  type LucideIcon,
} from "lucide-react";

export type Tab = "dashboard" | "calendar" | "profile";

interface Props {
  active: Tab;
  onChange: (tab: Tab) => void;
}

const TABS: { id: Tab; label: string; Icon: LucideIcon }[] = [
  { id: "dashboard", label: "Сегодня", Icon: LayoutDashboard },
  { id: "calendar", label: "Календарь", Icon: CalendarDays },
  { id: "profile", label: "Профиль", Icon: User },
];

export function TabBar({ active, onChange }: Props) {
  return (
    <Tabbar>
      {TABS.map(({ id, label, Icon }) => (
        <Tabbar.Item
          key={id}
          text={label}
          selected={active === id}
          onClick={() => onChange(id)}
        >
          <Icon size={22} strokeWidth={2} />
        </Tabbar.Item>
      ))}
    </Tabbar>
  );
}
