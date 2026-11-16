import type { Metadata, Viewport } from "next";
import { Instrument_Serif, Inter } from "next/font/google";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import Toaster from "@/components/Toaster";
import Tour from "@/components/Tour";
import AlertWatcher from "@/components/practice/AlertWatcher";
import { UserProvider } from "@/lib/useUser";
import { THEME_SCRIPT } from "@/lib/themeScript";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
// A display serif for the few words on the home page that carry the brand.
const display = Instrument_Serif({ subsets: ["latin"], weight: "400", style: ["normal", "italic"], variable: "--font-display", display: "swap" });

export const metadata: Metadata = {
  title: "Trading Lab: charts, backtests and paper trading",
  description: "Chart, backtest and practise trading gold, commodities, forex, indices, stocks and crypto, with news insights matched to your risk appetite.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0b0e12" },
    { media: "(prefers-color-scheme: light)", color: "#f5f3ee" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${inter.variable} ${display.variable}`} data-theme="dark" data-accent="gold" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="flex min-h-screen flex-col antialiased">
        <UserProvider>
          <Header />
          <main className="flex-1 overflow-x-clip">{children}</main>
          <Footer />
          <Toaster />
          <Tour />
          <AlertWatcher />
        </UserProvider>
      </body>
    </html>
  );
}
