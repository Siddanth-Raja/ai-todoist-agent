import type { Metadata, Viewport } from "next";
import { AppShell } from "@/components/app-shell";
import "./globals.css";
import { RuntimeSessionBoundary } from "@/components/runtime-session-boundary";

export const metadata: Metadata = {
  title: "Personal Chief of Staff",
  description: "Mobile-first command center for planning, chat, tasks, and memory.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="font-sans antialiased"><RuntimeSessionBoundary><AppShell>{children}</AppShell></RuntimeSessionBoundary></body>
    </html>
  );
}
