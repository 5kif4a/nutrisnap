import { AppRoot } from "@telegram-apps/telegram-ui";
import { User, Zap } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Onboarding } from "./components/Onboarding";
import { TabBar, type Tab } from "./components/TabBar";
import { api } from "./lib/api";
import { todayISO } from "./lib/date";
import { ToastProvider } from "./lib/toast";
import { Calendar } from "./pages/Calendar";
import { Dashboard } from "./pages/Dashboard";
import { MyFoods } from "./pages/MyFoods";
import { Profile } from "./pages/Profile";
import { useTelegramTheme } from "./telegram";
import type { UserProfile } from "./types";

export default function App() {
  useTelegramTheme();

  const [tab, setTab] = useState<Tab>("dashboard");
  const [date, setDate] = useState(todayISO());
  const [me, setMe] = useState<UserProfile | null>(null);
  const [meLoading, setMeLoading] = useState(true);

  const refetchMe = useCallback(async () => {
    try {
      const profile = await api.getMe();
      setMe(profile);
    } catch {
      // Network/auth hiccup — leave `me` null; the onboarding gate stays up
      // and the user can retry by re-opening the app.
      setMe(null);
    } finally {
      setMeLoading(false);
    }
  }, []);

  useEffect(() => {
    void refetchMe();
  }, [refetchMe]);

  const openDay = (iso: string) => {
    setDate(iso);
    setTab("dashboard");
  };

  const topInset = "max(env(safe-area-inset-top), 12px)";

  // The gate: until the user has computed daily targets we render *only*
  // the onboarding modal. No top-strip, no tab-bar, no FAB — that's exactly
  // what early friends wanted ("just don't show the UI until done").
  const onboardingNeeded =
    !meLoading && (me === null || me.targets.kcal == null);

  return (
    <AppRoot>
      <ToastProvider>
        {meLoading ? (
          <div className="flex min-h-full items-center justify-center text-sm text-tg-hint">
            <span className="h-6 w-6 animate-spin rounded-full border-2 border-tg-hint border-t-transparent" />
          </div>
        ) : onboardingNeeded ? (
          <Onboarding onComplete={refetchMe} />
        ) : (
          <div className="min-h-full">
            {tab === "dashboard" && (
              <Dashboard date={date} onDateChange={setDate} />
            )}
            {tab === "calendar" && <Calendar onSelectDay={openDay} />}
            {tab === "foods" && <MyFoods />}
            {tab === "profile" && <Profile />}

            {/* Global top strip — person → Profile + fake Pro upsell pill.
                Sits inside a centered max-w-md column so the controls track
                the app's content width on wide viewports. Person icon is
                hidden on the Profile page itself (you're already there). */}
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
        )}
      </ToastProvider>
    </AppRoot>
  );
}
