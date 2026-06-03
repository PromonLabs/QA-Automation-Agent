"use client"

import { useEffect, useState } from "react"
import { Wifi, WifiOff } from "lucide-react"
import { healthApi } from "@/lib/api"

export function Header({ title }: { title: string }) {
  const [llmStatus, setLlmStatus] = useState<"connected" | "disconnected" | "checking">("checking")

  useEffect(() => {
    const check = async () => {
      try {
        const { data } = await healthApi.check()
        setLlmStatus(data.llm === "connected" ? "connected" : "disconnected")
      } catch {
        setLlmStatus("disconnected")
      }
    }
    check()
    const t = setInterval(check, 30000)
    return () => clearInterval(t)
  }, [])

  return (
    <header className="flex items-center justify-between px-8 py-4 border-b border-white/10 bg-black/50 backdrop-blur-sm">
      <h1 className="text-white font-semibold text-lg">{title}</h1>
      <div className="flex items-center gap-2 text-xs">
        {llmStatus === "connected" ? (
          <div className="flex items-center gap-1.5 text-white/60">
            <div className="w-1.5 h-1.5 rounded-full bg-white animate-pulse2" />
            <span>Qwen2.5:14b online</span>
          </div>
        ) : llmStatus === "disconnected" ? (
          <div className="flex items-center gap-1.5 text-white/30">
            <div className="w-1.5 h-1.5 rounded-full bg-white/30" />
            <span>LLM offline</span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 text-white/20">
            <div className="w-1.5 h-1.5 rounded-full bg-white/20 animate-pulse" />
            <span>Connecting…</span>
          </div>
        )}
      </div>
    </header>
  )
}
