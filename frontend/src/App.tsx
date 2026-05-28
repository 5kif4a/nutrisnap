import { Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { AppRoot } from "@telegram-apps/telegram-ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { User, Zap } from "lucide-react";
import { Onboarding } from "./components/Onboarding";
import { TabBar } from "./components/TabBar";
import { meQuery } from "./queries";
import { ToastProvider } from "./lib/toast";
import { useTelegramTheme } from "./telegram";

export function RootLayout() {
  useTelegramTheme();

  const { data: me, isLoading: meLoading } = useQuery(meQuery());
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { location } = useRouterState();
  const isProfilePage = location.pathname === "/profile";

  const topInset = "max(env(safe-area-inset-top), 12px)";
  const onboardingNeeded = !meLoading && (!me || me.targets.kcal == null);

  if (meLoading) {
    return (
      <AppRoot>
        <AppSkeleton />
      </AppRoot>
    );
  }

  if (onboardingNeeded) {
    return (
      <AppRoot>
        <ToastProvider>
          <Onboarding
            onComplete={() =>
              void queryClient.invalidateQueries({ queryKey: ["me"] })
            }
          />
        </ToastProvider>
      </AppRoot>
    );
  }

  return (
    <AppRoot>
      <ToastProvider>
        <div className="min-h-full">
          <Outlet />

          {/* Global top strip — person icon → Profile + fake Pro upsell pill. */}
          <div
            className="pointer-events-none fixed inset-x-0 z-50"
            style={{ top: topInset }}
          >
            <div className="mx-auto flex max-w-md items-center gap-2 px-4">
              {!isProfilePage && (
                <button
                  type="button"
                  onClick={() => void navigate({ to: "/profile" })}
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

          <TabBar />
        </div>
      </ToastProvider>
    </AppRoot>
  );
}

export default RootLayout;

function AppSkeleton() {
  const topInset = "max(env(safe-area-inset-top), 12px)";

  return (
    <div className="min-h-full">
      {/* Top bar */}
      <div
        className="pointer-events-none fixed inset-x-0 z-50"
        style={{ top: topInset }}
      >
        <div className="mx-auto flex max-w-md items-center gap-2 px-4">
          <div className="skeleton h-10 w-10 rounded-full" />
          <div className="skeleton h-10 w-28 rounded-full" />
        </div>
      </div>

      {/* Dashboard content skeleton */}
      <div className="mx-auto max-w-md px-4 pb-32 pt-16">
        {/* Date label */}
        <div className="skeleton mx-auto mb-4 h-4 w-28 rounded-full" />

        {/* Week strip */}
        <div className="mb-4 grid grid-cols-7 gap-1.5">
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className="skeleton h-[52px] rounded-xl" />
          ))}
        </div>

        {/* Circular progress card */}
        <div className="mb-4 flex flex-col items-center rounded-2xl bg-white/[0.04] p-5">
          <div className="skeleton h-[120px] w-[120px] rounded-full" />
        </div>

        {/* Macro bars card */}
        <div className="mb-4 flex gap-4 rounded-2xl bg-white/[0.04] p-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="flex flex-1 flex-col gap-2">
              <div className="skeleton h-3 w-10 rounded-full" />
              <div className="skeleton h-[6px] w-full rounded-full" />
              <div className="skeleton h-3 w-8 rounded-full" />
            </div>
          ))}
        </div>

        {/* Meal card skeletons */}
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="mb-3 rounded-2xl bg-white/[0.04] p-4">
            <div className="skeleton mb-2 h-4 w-24 rounded-full" />
            <div className="skeleton h-3 w-40 rounded-full" />
          </div>
        ))}
      </div>

      {/* Bottom nav skeleton */}
      <nav className="fixed inset-x-0 bottom-0 z-50 flex justify-center pb-[max(env(safe-area-inset-bottom),12px)]">
        <div className="skeleton h-14 w-56 rounded-full" />
      </nav>
    </div>
  );
}
