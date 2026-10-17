import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "ISGEC AI — Engineering Assistant",
  description: "Project-based engineering workspace for equipment selection.",
};

/**
 * Identity is resolved once here and passed down. Phase 14 replaces
 * getCurrentUser() with Supabase Auth; pages keep reading `user` from the
 * layout, so nothing below changes.
 */
import { getCurrentUser } from "@/lib/auth";

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  let user = { fullName: "Bhavesh Konkar", email: null as string | null };
  try {
    const u = await getCurrentUser();
    user = { fullName: u.fullName, email: u.email };
  } catch (err) {
    // The shell must still render so the Projects page can show the real
    // reason rather than a blank 500. API routes fail closed regardless.
    console.error("[layout] identity unavailable:", (err as Error).message);
  }

  return (
    <html lang="en" className={`${inter.variable} dark`} suppressHydrationWarning>
      <body className="font-sans">{children}</body>
    </html>
  );
}