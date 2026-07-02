"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Brain,
  CalendarDays,
  CheckSquare,
  FolderKanban,
  MessageCircle,
  Repeat,
  Settings,
  Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

const navItems: Array<{
  href: string;
  label: string;
  description: string;
  icon: LucideIcon;
}> = [
  { href: "/today", label: "Today", description: "Personal operating view", icon: Sparkles },
  { href: "/projects", label: "Projects", description: "Project Brain", icon: FolderKanban },
  { href: "/chat", label: "Chat", description: "Assistant tool", icon: MessageCircle },
  { href: "/calendar", label: "Calendar", description: "Schedule view", icon: CalendarDays },
  { href: "/tasks", label: "Tasks", description: "Todoist focus list", icon: CheckSquare },
  { href: "/habits", label: "Habits", description: "Recurring routines", icon: Repeat },
  { href: "/memory", label: "Memory", description: "Personal context", icon: Brain },
  { href: "/settings", label: "Settings", description: "Connection details", icon: Settings },
];

function getCurrentItem(pathname: string) {
  return navItems.find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`)) ?? navItems[0];
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const currentItem = getCurrentItem(pathname);
  const isChatRoute = pathname === "/chat";

  return (
    <div className="h-screen overflow-hidden text-pearl">
      <div className="pointer-events-none fixed inset-0 -z-10 opacity-80">
        <div className="absolute left-[-8rem] top-24 h-72 w-72 rounded-full bg-iris/10 blur-3xl" />
        <div className="absolute right-[-10rem] top-10 h-96 w-96 rounded-full bg-moss/10 blur-3xl" />
      </div>

      <div className="mx-auto flex h-full w-full max-w-[1680px] gap-6 overflow-hidden px-3 pb-24 pt-3 md:px-6 lg:pb-6 xl:px-8">
        <aside className="sticky top-6 hidden h-[calc(100dvh-3rem)] w-72 shrink-0 rounded-[2rem] border border-white/10 bg-white/[0.055] p-3 shadow-soft backdrop-blur-2xl xl:block">
          <div className="px-4 pb-5 pt-4">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-pearl text-ink shadow-card">
              <Sparkles className="h-5 w-5" aria-hidden="true" />
            </div>
            <p className="text-xs font-medium uppercase tracking-[0.28em] text-moss">Personal OS</p>
            <h1 className="mt-2 text-2xl font-semibold tracking-normal text-pearl">Chief of Staff</h1>
            <p className="mt-3 text-sm leading-5 text-stone-400">
              A calm command surface for the next right move.
            </p>
          </div>
          <nav className="space-y-1.5">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = pathname === item.href;

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`group flex min-h-14 items-center gap-3 rounded-2xl px-4 transition ${
                    isActive
                      ? "bg-pearl text-ink shadow-card"
                      : "text-stone-400 hover:bg-white/[0.07] hover:text-pearl"
                  }`}
                >
                  <span
                    className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${
                      isActive ? "bg-black/5" : "bg-white/[0.06] group-hover:bg-white/[0.09]"
                    }`}
                  >
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </span>
                  <span>
                    <span className="block text-sm font-medium">{item.label}</span>
                    <span className={`block text-xs ${isActive ? "text-neutral-600" : "text-stone-500"}`}>
                      {item.description}
                    </span>
                  </span>
                </Link>
              );
            })}
          </nav>
        </aside>

        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <header className="z-20 shrink-0 px-2 pb-4 pt-[calc(env(safe-area-inset-top)+0.75rem)] md:px-0 md:pt-3">
            <div className="mx-auto flex w-[calc(100vw-2rem)] max-w-full items-center justify-between gap-4 rounded-[1.75rem] border border-white/10 bg-white/[0.045] px-4 py-3 shadow-card backdrop-blur-2xl sm:w-full md:px-5">
              <div>
                <p className="text-xs font-medium uppercase tracking-[0.24em] text-moss md:hidden">Personal OS</p>
                <h2 className="text-xl font-semibold tracking-normal text-pearl md:text-2xl">{currentItem.label}</h2>
                <p className="mt-1 text-sm text-stone-400">{currentItem.description}</p>
              </div>
              <div className="hidden items-center gap-2 rounded-full border border-white/10 bg-black/20 px-3 py-2 text-xs text-stone-400 md:flex">
                <span className="h-2 w-2 rounded-full bg-moss shadow-[0_0_18px_rgba(167,232,196,0.7)]" />
                Live day
              </div>
            </div>
          </header>

          <main
            className={`min-h-0 min-w-0 flex-1 px-1 pt-1 md:px-0 ${
              isChatRoute ? "overflow-hidden" : "overflow-y-auto overflow-x-hidden"
            }`}
          >
            {children}
          </main>
        </div>
      </div>

      <nav className="fixed inset-x-0 bottom-0 z-30 px-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] xl:hidden">
        <div className="mx-auto grid max-w-lg grid-cols-8 gap-1 rounded-[1.6rem] border border-white/10 bg-black/55 p-2 shadow-soft backdrop-blur-2xl">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = pathname === item.href;

            return (
              <Link
                key={item.href}
                href={item.href}
                aria-label={item.label}
                className={`flex min-h-14 flex-col items-center justify-center gap-1 rounded-[1.1rem] text-[11px] font-medium transition ${
                  isActive ? "bg-pearl text-ink shadow-card" : "text-stone-500 hover:bg-white/10 hover:text-pearl"
                }`}
              >
                <Icon className="h-5 w-5" aria-hidden="true" />
                <span className="hidden max-w-full truncate sm:block">{item.label}</span>
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
