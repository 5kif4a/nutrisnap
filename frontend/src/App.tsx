import { AppRoot } from "@telegram-apps/telegram-ui";
import { User, Zap } from "lucide-react";
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

  const topInset = "max(env(safe-area-inset-top), 12px)";

  return (
    <AppRoot>
      <ToastProvider>
        <div className="min-h-full">
          {tab === "dashboard" && (
            <Dashboard date={date} onDateChange={setDate} />
          )}
          {tab === "calendar" && <Calendar onSelectDay={openDay} />}
          {tab === "foods" && <MyFoods />}
          {tab === "profile" && <Profile />}

          {/* Global top strip — person → Profile + fake Pro upsell pill.
              Sits inside a centered max-w-md column so the controls track the
              app's content width on wide viewports. Person icon is hidden on
              the Profile page itself (you're already there). */}
          <div
            className="pointer-events-none fixed inset-x-0 z-50"
            style={{ top: topInset }}
          >
            <div className="mx-auto flex max-w-md items-center gap-2 px-4">
              {tab !== "profile" && (
                <button
                  type="button"
                  onClick={() => setTab("profile")}
                  aria-label="Открыть профиль"
                  className="liquid-glass-soft pointer-events-auto flex h-10 w-10 items-center justify-center rounded-full text-tg-text active:scale-90"
                >
                  <User size={20} />
                </button>
              )}

              <button
                type="button"
                onClick={() => {
                  /* fake Pro pill — coming soon */
                }}
                className="pointer-events-auto flex h-10 items-center gap-1.5 rounded-full px-3.5 text-sm font-semibold text-white shadow-sm active:scale-95"
                style={{
                  background:
                    "linear-gradient(135deg, var(--accent), rgba(120,92,220,0.95))",
                }}
              >
                <Zap size={14} fill="currentColor" strokeWidth={0} />
                <span>Купить Pro</span>
              </button>
            </div>
          </div>

          <TabBar active={tab} onChange={setTab} />
        </div>
      </ToastProvider>
    </AppRoot>
  );
}
