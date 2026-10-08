import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Menu } from "lucide-react";
import { MarketStatusPill } from "@/components/shell/market-status";
import { SideNav } from "@/components/shell/nav";
import { StockSearch } from "@/components/shell/search";
import { Wordmark } from "@/components/shell/logo";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono-face" });

export const metadata: Metadata = {
  title: { default: "DhanDrishti", template: "%s · DhanDrishti" },
  description: "See the signal. Understand the stock. Explainable research for Indian equities.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN" className={`${inter.variable} ${mono.variable}`}>
      <body className="min-h-dvh">
        <div className="flex min-h-dvh">
          <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col gap-6 overflow-y-auto border-r border-line px-4 py-5 lg:flex">
            <Wordmark />
            <SideNav />
          </aside>

          <div className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-20 flex items-center gap-4 border-b border-line bg-bg/80 px-4 py-3 backdrop-blur md:px-6">
              <details className="relative lg:hidden">
                <summary className="flex cursor-pointer list-none items-center rounded-md p-2 text-muted hover:text-ink" aria-label="Menu">
                  <Menu className="size-5" />
                </summary>
                <div className="absolute left-0 z-40 mt-2 w-64 rounded-xl border border-line-strong bg-surface p-3 shadow-2xl">
                  <SideNav />
                </div>
              </details>
              <div className="lg:hidden">
                <span className="text-sm font-bold tracking-[0.14em]">DHANDRISHTI</span>
              </div>
              <StockSearch />
              <div className="ml-auto">
                <MarketStatusPill />
              </div>
            </header>

            <main className="mx-auto w-full max-w-[1440px] flex-1 px-4 py-6 md:px-6">{children}</main>

            <footer className="border-t border-line px-4 py-4 text-[11px] leading-relaxed text-faint md:px-6">
              DhanDrishti provides research and analytical information for educational and decision-support purposes only.
              It is not investment advice or a recommendation to buy, sell or hold any security. Scores are outputs of a
              quantitative model and may be wrong. Consult a SEBI-registered adviser before investing.
            </footer>
          </div>
        </div>
      </body>
    </html>
  );
}
