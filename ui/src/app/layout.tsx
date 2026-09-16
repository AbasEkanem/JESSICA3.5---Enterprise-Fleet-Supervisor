import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "./jessica.css";

import "./greeting-variants.css";
import { ThemeProvider } from "@/context/ThemeContext";
import { AuthProvider } from "@/context/AuthProvider";

const jakarta = Plus_Jakarta_Sans({ subsets: ["latin"], variable: "--font-jakarta" });

export const metadata: Metadata = {
  title: "Jessica 3.5 — Deep Research AI",
  description: "Multi-source investigative AI agent. Powered by Tavily, Exa, SerperDev, SerpAPI & DuckDuckGo.",
  keywords: ["Jessica AI", "deep research", "AI agent", "investigative intelligence"],
};

// Pre-hydration theme bootstrap — runs synchronously in <head> BEFORE first paint
// so the correct day/night palette is applied immediately and the page never
// flashes the wrong theme on load (the previous behaviour: SSR shipped
// data-theme="dark", so a daytime "auto" load painted dark, then ThemeContext's
// post-hydration effect flipped it to light — a visible flash). This mirrors
// ThemeContext EXACTLY: same storage keys ("jessica-theme-pref", legacy
// "jessica-theme"), same default ("auto"), and the same time-of-day rule
// (07:00–18:59 → light, otherwise dark). ThemeContext then takes over on
// hydration and keeps re-resolving on its 60s timer.
const themeInitScript =
  "(function(){try{var p=localStorage.getItem('jessica-theme-pref');" +
  "if(p!=='dark'&&p!=='light'&&p!=='auto'){var l=localStorage.getItem('jessica-theme');" +
  "p=(l==='dark'||l==='light')?l:'auto';}" +
  "var h=new Date().getHours();var t=p==='auto'?(h>=7&&h<19?'light':'dark'):p;" +
  "var e=document.documentElement;e.setAttribute('data-theme',t);" +
  "e.setAttribute('data-theme-pref',p);}catch(err){}})();";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <head>
        {/* Must be the first thing in <head> so it runs before any paint. */}
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className={`${jakarta.variable}`} style={{ fontFamily: "'Plus Jakarta Sans', 'Google Sans', system-ui, -apple-system, sans-serif" }}>
        <AuthProvider>
          <ThemeProvider>{children}</ThemeProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
