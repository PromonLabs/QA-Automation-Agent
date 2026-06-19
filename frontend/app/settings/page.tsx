"use client"

import { useEffect, useState } from "react"
import { healthApi, agentSettingsApi } from "@/lib/api"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import { Loader2, CheckCircle2, XCircle, RefreshCw, Copy } from "lucide-react"

export default function SettingsPage() {
  const [health, setHealth] = useState<any>(null)
  const [checking, setChecking] = useState(true)
  const [copied, setCopied] = useState("")
  const [togglingAgent, setTogglingAgent] = useState<string | null>(null)

  const check = async () => {
    setChecking(true)
    try {
      const { data } = await healthApi.check()
      setHealth(data)
    } catch {
      setHealth({ status: "error", llm: "disconnected", browser: "unknown" })
    } finally {
      setChecking(false)
    }
  }

  const toggleAgent = async (key: "use_flow_agent" | "use_vision_agent", current: boolean) => {
    setTogglingAgent(key)
    try {
      await agentSettingsApi.update({ [key]: !current })
      await check()
    } catch {
      // ignore
    } finally {
      setTogglingAgent(null)
    }
  }

  useEffect(() => { check() }, [])

  const copyCmd = (cmd: string) => {
    navigator.clipboard.writeText(cmd)
    setCopied(cmd)
    setTimeout(() => setCopied(""), 2000)
  }

  const checks = health ? [
    { label: "Backend API",      ok: health.status !== "error",   detail: health.status },
    { label: "Vision Agent",     ok: health.vision === "connected", detail: health.vision === "connected" ? "online" : "offline", fix: health.vision !== "connected" ? "ollama serve" : null },
    { label: "Chromium Browser", ok: health.browser === "ready",  detail: health.browser === "ready" ? "installed" : "not installed", fix: health.browser !== "ready" ? "python -m playwright install chromium" : null },
  ] : []

  return (
    <div className="flex min-h-screen bg-black">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Header title="Settings" />
        <main className="flex-1 p-8 max-w-2xl space-y-6">

          {/* System Health */}
          <div className="bg-white/[0.03] border border-white/10 rounded-xl p-6">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-white font-semibold">System Health</h2>
              <button onClick={check} disabled={checking}
                className="flex items-center gap-1.5 text-white/30 hover:text-white text-xs transition-colors">
                <RefreshCw className={`w-3.5 h-3.5 ${checking ? "animate-spin" : ""}`} />
                Refresh
              </button>
            </div>
            {checking ? (
              <div className="flex justify-center py-8"><Loader2 className="animate-spin text-white/20" /></div>
            ) : (
              <div className="space-y-3">
                {checks.map(({ label, ok, detail, fix }: any) => (
                  <div key={label} className="border-b border-white/5 last:border-0 pb-3 last:pb-0">
                    <div className="flex items-center justify-between">
                      <span className="text-white/50 text-sm">{label}</span>
                      <div className="flex items-center gap-1.5 text-sm">
                        {ok
                          ? <><CheckCircle2 className="w-4 h-4 text-white" /><span className="text-white">{detail}</span></>
                          : <><XCircle className="w-4 h-4 text-white/30" /><span className="text-white/30">{detail}</span></>}
                      </div>
                    </div>
                    {fix && (
                      <div className="mt-2 flex items-center gap-2">
                        <code className="text-white/40 text-xs bg-white/5 px-3 py-1.5 rounded font-mono flex-1">{fix}</code>
                        <button onClick={() => copyCmd(fix)} className="text-white/30 hover:text-white p-1.5 transition-colors">
                          {copied === fix ? <CheckCircle2 className="w-3.5 h-3.5 text-white" /> : <Copy className="w-3.5 h-3.5" />}
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Agent Toggles */}
          <div className="bg-white/[0.03] border border-white/10 rounded-xl p-6">
            <h2 className="text-white font-semibold mb-5">Agents</h2>
            <div className="space-y-4">
              {[
                {
                  key: "use_flow_agent" as const,
                  label: "Flow Agent",
                  sub: health?.llm_provider === "claude"
                    ? `LLM planning via ${health?.llm_provider_label || "Claude API"}`
                    : "LLM-based step planning (requires Ollama)",
                  enabled: health?.flow_agent_enabled ?? false,
                  status: health?.llm,
                },
                {
                  key: "use_vision_agent" as const,
                  label: "Vision Agent",
                  sub: "Screen element detection via vision model",
                  enabled: health?.vision_agent_enabled ?? true,
                  status: health?.vision,
                },
              ].map(({ key, label, sub, enabled, status }) => (
                <div key={key} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
                  <div>
                    <p className="text-white/70 text-sm font-medium">{label}</p>
                    <p className="text-white/30 text-xs mt-0.5">{sub}</p>
                    {status && (
                      <p className={`text-xs mt-0.5 ${status === "connected" ? "text-white/40" : "text-white/20"}`}>
                        {status === "connected" ? "model online" : "model offline"}
                      </p>
                    )}
                  </div>
                  <button
                    onClick={() => toggleAgent(key, enabled)}
                    disabled={togglingAgent === key || checking}
                    className={`relative w-11 h-6 rounded-full transition-colors duration-200 focus:outline-none ${
                      enabled ? "bg-white/70" : "bg-white/10"
                    } ${togglingAgent === key ? "opacity-50" : ""}`}
                  >
                    <span
                      className={`absolute top-0.5 left-0.5 w-5 h-5 bg-black rounded-full shadow transition-transform duration-200 ${
                        enabled ? "translate-x-5" : "translate-x-0"
                      }`}
                    />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Quick Setup */}
          <div className="bg-white/[0.03] border border-white/10 rounded-xl p-6">
            <h2 className="text-white font-semibold mb-4">Quick Setup Commands</h2>
            <div className="space-y-2">
              {[
                { label: "Start Ollama LLM",        cmd: "ollama serve" },
                { label: "Pull qwen2.5:7b model",     cmd: "ollama pull qwen2.5:7b" },
                { label: "Install Chromium browser", cmd: "python -m playwright install chromium" },
                { label: "Start backend",            cmd: ".\\start-backend.ps1" },
                { label: "Start frontend",           cmd: ".\\start-frontend.ps1" },
              ].map(({ label, cmd }) => (
                <div key={label} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
                  <span className="text-white/40 text-xs">{label}</span>
                  <div className="flex items-center gap-2">
                    <code className="text-white/60 text-xs font-mono">{cmd}</code>
                    <button onClick={() => copyCmd(cmd)} className="text-white/20 hover:text-white/60 p-1 transition-colors">
                      {copied === cmd ? <CheckCircle2 className="w-3 h-3 text-white" /> : <Copy className="w-3 h-3" />}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Config */}
          <div className="bg-white/[0.03] border border-white/10 rounded-xl p-6">
            <h2 className="text-white font-semibold mb-4">Configuration</h2>
            <div className="space-y-2 text-sm">
              {[
                { k: "LLM Provider", v: health?.llm_provider_label || "Ollama (qwen2.5:14b)" },
                { k: "Claude Key",   v: health?.claude_key_set ? "configured" : "not set" },
                { k: "Ollama Host",  v: health?.ollama_host || "http://localhost:11434" },
                { k: "API",          v: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000" },
                { k: "Login",        v: "admin / admin123" },
              ].map(({ k, v }) => (
                <div key={k} className="flex justify-between py-1.5 border-b border-white/5 last:border-0">
                  <span className="text-white/30">{k}</span>
                  <span className="text-white/60 font-mono text-xs">{v}</span>
                </div>
              ))}
            </div>
          </div>

        </main>
      </div>
    </div>
  )
}
