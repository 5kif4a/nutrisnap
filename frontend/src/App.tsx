import { useState } from "react";
import { TabBar, type Tab } from "./components/TabBar";
import { Dashboard } from "./pages/Dashboard";
import { Profile } from "./pages/Profile";
import { useTelegramTheme } from "./telegram";

export default function App() {
  useTelegramTheme();
  const [tab, setTab] = useState<Tab>("dashboard");
  return (
    <div className="min-h-full bg-tg-bg">
      {tab === "dashboard" ? <Dashboard /> : <Profile />}
      <TabBar active={tab} onChange={setTab} />
    </div>
  );
}
