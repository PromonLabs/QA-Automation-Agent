"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { healthApi } from "@/lib/api"
import { Server, HardDrive, Cloud, Sparkles, Settings2 } from "lucide-react"

type AgentStatus = "connected" | "disconnected" | "checking"
type Provider = "ollama" | "claude" | "gateway" | "gemini"

export function Header({ title }: { title: string }) {
  const [visionStatus,     setVisionStatus]     = useState<AgentStatus>("checking")
  const [visionModel,      setVisionModel]      = useState("qwen2.5:7b")
  const [flowAgentEnabled, setFlowAgentEnabled] = useState(false)
  const [llmStatus,        setLlmStatus]        = useState<AgentStatus>("checking")
  const [llmModel,         setLlmModel]         = useState("qwen2.5:7b")
  const [provider,         setProvider]         = useState<Provider>("ollama")

  useEffect(() => {
    const check = async () => {
      try {
        const { data } = await healthApi.check()
        setVisionStatus(data.vision === "connected" ? "connected" : "disconnected")
        if (data.vision_model) setVisionModel(data.vision_model.replace(":latest", ""))
        setFlowAgentEnabled(!!data.flow_agent_enabled)
        setLlmStatus(data.llm === "connected" ? "connected" : "disconnected")
        if (data.model) setLlmModel(data.model)
        if (data.llm_provider) setProvider(data.llm_provider)
      } catch {
        setVisionStatus("disconnected")
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

      <div className="flex items-center gap-4 text-xs">
        {flowAgentEnabled && (
          <AgentBadge label={llmModel} role="Flow Agent" status={llmStatus} provider={provider} />
        )}
        <AgentBadge label={visionModel} role="Vision Agent" status={visionStatus} />
        <Link
          href="/settings"
          title="Switch between Gateway and Local model"
          className="flex items-center gap-1.5 text-white/30 hover:text-white border border-white/10 hover:border-white/30 rounded-md px-2 py-1 transition-colors"
        >
          <Settings2 className="w-3.5 h-3.5" />
          Switch model
        </Link>
      </div>
    </header>
  )
}

const PROVIDER_META: Record<Provider, { label: string; icon: typeof Server }> = {
  gateway: { label: "Gateway", icon: Server },
  ollama:  { label: "Local",   icon: HardDrive },
  claude:  { label: "Claude",  icon: Cloud },
  gemini:  { label: "Gemini",  icon: Sparkles },
}

function AgentBadge({
  label, role, status, provider,
}: {
  label: string
  role: string
  status: AgentStatus
  provider?: Provider
}) {
  const meta = provider ? PROVIDER_META[provider] : null
  const ProviderIcon = meta?.icon

  const providerTag = meta && (
    <span className="flex items-center gap-1 text-white/40 bg-white/5 border border-white/10 rounded px-1.5 py-0.5">
      {ProviderIcon && <ProviderIcon className="w-3 h-3" />}
      {meta.label}
    </span>
  )

  if (status === "connected") {
    return (
      <div className="flex items-center gap-1.5 text-white/60">
        <div className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
        <span className="text-white/40">{role}:</span>
        <span>{label} online</span>
        {providerTag}
      </div>
    )
  }
  if (status === "disconnected") {
    return (
      <div className="flex items-center gap-1.5 text-white/30">
        <div className="w-1.5 h-1.5 rounded-full bg-red-500/60" />
        <span className="text-white/30">{role}:</span>
        <span>{label} offline</span>
        {providerTag}
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
