/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Mapped to Telegram theme CSS vars (with sane light-mode fallbacks).
        tg: {
          bg: "var(--tg-bg)",
          card: "var(--tg-card)",
          text: "var(--tg-text)",
          hint: "var(--tg-hint)",
          link: "var(--tg-link)",
          button: "var(--tg-button)",
          "button-text": "var(--tg-button-text)",
          border: "var(--tg-border)",
        },
      },
    },
  },
  plugins: [],
};
