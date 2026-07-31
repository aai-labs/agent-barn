import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google"; // ui fonts test

import { NuqsAdapter } from "nuqs/adapters/next/app";

import { QueryProvider } from "@/shared/providers/query-provider";
import { AppProvider } from "@/shared/providers/app-provider";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";
import { cn } from "@/lib/utils";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Agent Barn",
  description: "Manage your AI agent workforce.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={cn(
        "h-full",
        "antialiased",
        geistSans.variable,
        geistMono.variable,
        "font-sans",
      )}
    >
      <body className="min-h-full flex flex-col">
        <NuqsAdapter>
          <QueryProvider>
            <TooltipProvider>
              <AppProvider>{children}</AppProvider>
              <Toaster />
            </TooltipProvider>
          </QueryProvider>
        </NuqsAdapter>
      </body>
    </html>
  );
}
