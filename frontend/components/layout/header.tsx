"use client"

import { useEffect, useState } from "react"
import { healthApi } from "@/lib/api"

type AgentStatus = "connected" | "disconnected" | "checking"

export function Header({ title }: { title: string }) {
  const [llmStatus, setLlmStatus]       = useState<AgentStatus>("checking")
  const [visionStatus, setVisionStatus] = useState<AgentStatus>("checking")

  useEffect(() => {
    const check = async () => {
      try {
        const { data } = await healthApi.check()
        setLlmStatus(data.llm === "connected" ? "connected" : "disconnected")
        setVisionStatus(data.vision === "connected" ? "connected" : "disconnected")
      } catch {
        setLlmStatus("disconnected")
        setVisionStatus("disconnected")
      }
    }
    check()
    const t = setInterval(check, 30000)
    return () => clearInterval(t)
  }, [])

  return (
    <header className="flex items-center justify-between px-8 py-4 border-b border-white/10 bg-black/50 backdrop-blur-sm">
      <h1 className="text-white font-semibold text-lg">{title}</h1>

      <div className="flex items-center gap-4 text-xs">
        {/* Flow Parser — qwen2.5:14b */}
        <AgentBadge
          label="qwen2.5:14b"
          role="Flow Agent"
          status={llmStatus}
        />

        {/* Screen Vision — qwen2.5vl */}
        <AgentBadge
          label="qwen2.5vl"
          role="Vision Agent"
          status={visionStatus}
        />
      </div>
    </header>
  )
}

function AgentBadge({
  label,
  role,
  status,
}: {
  label: string
  role: string
  status: AgentStatus
}) {
  if (status === "connected") {
    return (
      <div className="flex items-center gap-1.5 text-white/60">
        <div className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
        <span className="text-white/40">{role}:</span>
        <span>{label} online</span>
      </div>
    )
  }
  if (status === "disconnected") {
    return (
      <div className="flex items-center gap-1.5 text-white/30">
        <div className="w-1.5 h-1.5 rounded-full bg-red-500/60" />
        <span className="text-white/30">{role}:</span>
        <span>{label} offline</span>
      </div>
    )
  }
  return (
    <div className="flex items-center gap-1.5 text-white/20">
      <div className="w-1.5 h-1.5 rounded-full bg-white/20 animate-pulse" />
      <span>{role}: connecting…</span>
    </div>
  )
}
