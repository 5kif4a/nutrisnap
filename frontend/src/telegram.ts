/**
 * Telegram integration via @telegram-apps/sdk-react (course-required stack).
 *
 * Public API is intentionally stable (getInitData / applyTheme / initTelegram
 * / closeToBot / greetingName / isInTelegram / useTelegramTheme) so the rest
 * of the app (api.ts, pages) does not depend on the SDK directly.
 *
 * Runs both inside Telegram and in a plain browser: outside Telegram the SDK
 * signals stay empty and we fall back to VITE_TEST_INIT_DATA + default theme.
 */

import { useEffect } from "react";
import {
  closeMiniApp,
  expandViewport,
  init,
  initDataUser,
  isMiniAppDark,
  isTMA,
  mountMiniAppSync,
  mountThemeParamsSync,
  restoreInitData,
  retrieveRawInitData,
  themeParamsState,
  useSignal,
  type ThemeParams,
} from "@telegram-apps/sdk-react";

let inTelegram = false;

export function isInTelegram(): boolean {
  return inTelegram;
}

/** Raw initData for the X-Init-Data header; empty in a plain browser (→ dev user). */
export function getInitData(): string {
  try {
    const raw = retrieveRawInitData();
    if (raw) return raw;
  } catch {
    /* not in Telegram */
  }
  return import.meta.env.VITE_TEST_INIT_DATA || "";
}

export function greetingName(): string {
  try {
    const user = initDataUser();
    if (user?.first_name) return user.first_name;
  } catch {
    /* no init data */
  }
  return "друг";
}

/** Map Telegram theme params onto our CSS custom properties. */
export function applyTheme(): void {
  const root = document.documentElement;

  let params: ThemeParams = {};
  let dark = false;
  try {
    params = themeParamsState();
    dark = isMiniAppDark();
  } catch {
    /* signals not mounted (browser) — use fallbacks */
  }

  const set = (name: string, value: string | undefined, fallback: string) => {
    root.style.setProperty(name, value || fallback);
  };

  set("--tg-bg", params.bg_color, dark ? "#17212b" : "#f4f4f5");
  set("--tg-card", params.secondary_bg_color, dark ? "#232e3c" : "#ffffff");
  set("--tg-text", params.text_color, dark ? "#ffffff" : "#0f172a");
  set("--tg-hint", params.hint_color, dark ? "#7d8b99" : "#94a3b8");
  set("--tg-link", params.link_color, "#3b82f6");
  set("--tg-button", params.button_color, "#3b82f6");
  set("--tg-button-text", params.button_text_color, "#ffffff");
  set("--tg-border", undefined, dark ? "#33455a" : "#e5e7eb");
}

export function initTelegram(): void {
  try {
    inTelegram = isTMA();
  } catch {
    inTelegram = false;
  }

  if (inTelegram) {
    try {
      init();
      restoreInitData();
      mountMiniAppSync();
      mountThemeParamsSync();
      try {
        expandViewport();
      } catch {
        /* viewport optional */
      }
    } catch (e) {
      console.warn("Telegram SDK init failed — browser fallback", e);
      inTelegram = false;
    }
  }

  applyTheme();
}

/** React hook: re-apply CSS theme whenever Telegram theme/scheme changes. */
export function useTelegramTheme(): void {
  const params = useSignal(themeParamsState);
  const dark = useSignal(isMiniAppDark);
  useEffect(() => {
    applyTheme();
  }, [params, dark]);
}

/** Close the Mini App (returns user to the chat to send a photo/voice/text). */
export function closeToBot(): void {
  try {
    closeMiniApp();
  } catch {
    /* no-op outside Telegram */
  }
}
