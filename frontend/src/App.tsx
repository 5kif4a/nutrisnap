import { AppRoot } from "@telegram-apps/telegram-ui";
import { Settings, X } from "lucide-react";
import { useState } from "react";
import { TabBar, type Tab } from "./components/TabBar";
import { todayISO } from "./lib/date";
import { ToastProvider } from "./lib/toast";
import { Calendar } from "./pages/Calendar";
import { Dashboard } from "./pages/Dashboard";
import { MyFoods } from "./pages/MyFoods";
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
      <ToastProvider>
        <div className="min-h-full">
          {tab === "dashboard" && (
            <Dashboard date={date} onDateChange={setDate} />
          )}
          {tab === "calendar" && (
            <Calendar
              onSelectDay={openDay}
              onBack={() => setTab("dashboard")}
            />
          )}
          {tab === "foods" && <MyFoods />}
          {tab === "profile" && <Profile />}

          {/* Global top-right action button: gear → open Settings (Profile),
              X → close Settings back to Dashboard. Fixed so it stays visible
              regardless of page scroll. Sits above the bottom-nav z-index. */}
          <button
            type="button"
            onClick={() =>
              setTab(tab === "profile" ? "dashboard" : "profile")
            }
            aria-label={
              tab === "profile" ? "Закрыть настройки" : "Открыть настройки"
            }
            className="liquid-glass fixed right-3 z-50 flex h-10 w-10 items-center justify-center rounded-full text-tg-text active:scale-90"
            style={{
              top: "max(env(safe-area-inset-top), 12px)",
            }}
          >
            {tab === "profile" ? <X size={18} /> : <Settings size={18} />}
          </button>

          <TabBar active={tab} onChange={setTab} />
        </div>
      </ToastProvider>
    </AppRoot>
  );
}
