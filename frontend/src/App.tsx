import { AppRoot } from "@telegram-apps/telegram-ui";
import { useState } from "react";
import { TabBar, type Tab } from "./components/TabBar";
import { todayISO } from "./lib/date";
import { Calendar } from "./pages/Calendar";
import { Dashboard } from "./pages/Dashboard";
import { Profile } from "./pages/Profile";
import { useTelegramTheme } from "./telegram";

export default function App() {
  useTelegramTheme();
  const [tab, setTab] = useState<Tab>("dashboard");
  const [date, setDate] = useState(todayISO());

  const openDay = (iso: string) => {
    setDate(iso);
    setTab("dashboard");
  };

  return (
    <AppRoot>
      <div className="min-h-full bg-tg-bg">
        {tab === "dashboard" && (
          <Dashboard date={date} onDateChange={setDate} />
        )}
        {tab === "calendar" && <Calendar onSelectDay={openDay} />}
        {tab === "profile" && <Profile />}
        <TabBar active={tab} onChange={setTab} />
      </div>
    </AppRoot>
  );
}
