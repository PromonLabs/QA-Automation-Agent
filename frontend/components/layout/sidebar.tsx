"use client"

import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import {
  LayoutDashboard,
  Play,
  ScrollText,
  Settings,
  LogOut,
  Bot,
  Activity,
  FileBadge,
  PenLine,
  KeyRound,
  Layers,
  BarChart2,
} from "lucide-react"
import { cn } from "@/lib/utils"

const nav = [
  { href: "/dashboard",  label: "Dashboard",    icon: LayoutDashboard },
  { href: "/flows",      label: "Flows",         icon: Play },
  { href: "/flows/new",  label: "Write Flow",    icon: PenLine },
  { href: "/execution",  label: "Executions",    icon: Activity },
  { href: "/bulk",       label: "Bulk Run",      icon: Layers },
  { href: "/bulk/results", label: "Bulk Results", icon: BarChart2 },
  { href: "/reports",    label: "Reports",       icon: FileBadge },
  { href: "/env",        label: "Environment",   icon: KeyRound },
  { href: "/settings",   label: "Settings",      icon: Settings },
]

export function Sidebar() {
  const pathname = usePathname()
  const router = useRouter()

  const logout = () => {
    localStorage.removeItem("token")
    router.push("/login")
  }

  return (
    <aside className="flex flex-col w-60 min-h-screen bg-black border-r border-white/10 shrink-0">
      {/* Logo */}
      <div className="flex items-center gap-3 px-6 py-5 border-b border-white/10">
        <div className="flex items-center justify-center w-8 h-8 bg-white rounded-sm">
          <Bot className="w-5 h-5 text-black" />
        </div>
        <div>
          <div className="text-white font-semibold text-sm leading-none">QA Automation Agent</div>
          <div className="text-white/30 text-xs mt-0.5">AI Browser Platform</div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {nav.map(({ href, label, icon: Icon }) => {
          const active =
            href === "/flows/new"
              ? pathname === "/flows/new"
              : href === "/flows"
              ? pathname === "/flows" || pathname.startsWith("/flows/edit")
              : href === "/bulk"
              ? pathname === "/bulk" || (pathname.startsWith("/bulk/") && !pathname.startsWith("/bulk/results"))
              : href === "/bulk/results"
              ? pathname === "/bulk/results"
              : pathname === href || (href !== "/dashboard" && pathname.startsWith(href))
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-all",
                active
                  ? "bg-white text-black font-medium"
                  : "text-white/50 hover:text-white hover:bg-white/5"
              )}
            >
              <Icon className="w-4 h-4 shrink-0" />
              {label}
            </Link>
          )
        })}
      </nav>

      {/* Bottom */}
      <div className="px-3 py-4 border-t border-white/10">
        <button
          onClick={logout}
          className="flex items-center gap-3 px-3 py-2 w-full rounded-md text-sm text-white/40 hover:text-white hover:bg-white/5 transition-all"
        >
          <LogOut className="w-4 h-4" />
          Sign Out
        </button>
      </div>
    </aside>
  )
}
