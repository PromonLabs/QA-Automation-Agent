"use client"

import { useEffect, useState } from "react"
import { healthApi, agentSettingsApi, llmSettingsApi } from "@/lib/api"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import { Loader2, CheckCircle2, XCircle, RefreshCw, Copy, Plus, Trash2, Cloud, HardDrive, Server, Sparkles, Eye, Type } from "lucide-react"

type LlmModel = { name: string; size?: number; modified_at?: string }
type LlmSettings = {
  provider: "ollama" | "claude" | "gateway" | "gemini"
  ollama_host: string
  ollama_reachable: boolean
  text_model: string
  vision_model: string
  claude_model: string
  claude_key_set: boolean
  gateway_base_url: string
  gateway_model: string
  gateway_vision_model: string
  gateway_key_set: boolean
  gemini_model: string
  gemini_vision_model: string
  gemini_key_set: boolean
  gemini_usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number; calls: number; updated_at?: string }
  models: LlmModel[]
}

function formatTokens(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function formatSize(bytes?: number) {
  if (!bytes) return ""
  const gb = bytes / 1024 ** 3
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${(bytes / 1024 ** 2).toFixed(0)} MB`
}

export default function SettingsPage() {
  const [health, setHealth] = useState<any>(null)
  const [checking, setChecking] = useState(true)
  const [copied, setCopied] = useState("")
  const [togglingAgent, setTogglingAgent] = useState<string | null>(null)

  const [llm, setLlm] = useState<LlmSettings | null>(null)
  const [llmLoading, setLlmLoading] = useState(true)
  const [llmBusy, setLlmBusy] = useState<string | null>(null)
  const [newModelName, setNewModelName] = useState("")
  const [pulling, setPulling] = useState(false)
  const [llmError, setLlmError] = useState("")

  const [gatewayTextModel, setGatewayTextModel] = useState("")
  const [gatewayVisionModel, setGatewayVisionModel] = useState("")
  const [geminiTextModel, setGeminiTextModel] = useState("")
  const [geminiVisionModel, setGeminiVisionModel] = useState("")

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

  const loadLlms = async () => {
    setLlmLoading(true)
    try {
      const { data } = await llmSettingsApi.list()
      setLlm(data)
      setGatewayTextModel(data.gateway_model || "")
      setGatewayVisionModel(data.gateway_vision_model || "")
      setGeminiTextModel(data.gemini_model || "")
      setGeminiVisionModel(data.gemini_vision_model || "")
    } catch {
      setLlm(null)
    } finally {
      setLlmLoading(false)
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

  const setProvider = async (provider: "ollama" | "claude" | "gateway" | "gemini") => {
    setLlmBusy("provider")
    try {
      await llmSettingsApi.update({ provider })
      await Promise.all([loadLlms(), check()])
    } catch {
      // ignore
    } finally {
      setLlmBusy(null)
    }
  }

  const saveGatewayModels = async () => {
    setLlmBusy("gateway")
    try {
      await llmSettingsApi.update({
        gateway_model: gatewayTextModel.trim(),
        gateway_vision_model: gatewayVisionModel.trim(),
      })
      await Promise.all([loadLlms(), check()])
    } catch {
      // ignore
    } finally {
      setLlmBusy(null)
    }
  }

  const saveGeminiModels = async () => {
    setLlmBusy("gemini")
    try {
      await llmSettingsApi.update({
        gemini_model: geminiTextModel.trim(),
        gemini_vision_model: geminiVisionModel.trim(),
      })
      await Promise.all([loadLlms(), check()])
    } catch {
      // ignore
    } finally {
      setLlmBusy(null)
    }
  }

  const setActiveModel = async (role: "text_model" | "vision_model", name: string) => {
    setLlmBusy(role + name)
    try {
      await llmSettingsApi.update({ [role]: name })
      await Promise.all([loadLlms(), check()])
    } catch {
      // ignore
    } finally {
      setLlmBusy(null)
    }
  }

  const removeModel = async (name: string) => {
    setLlmBusy("remove" + name)
    try {
      await llmSettingsApi.remove(name)
      await loadLlms()
    } catch {
      // ignore
    } finally {
      setLlmBusy(null)
    }
  }

  const pullModel = async () => {
    const name = newModelName.trim()
    if (!name) return
    setPulling(true)
    setLlmError("")
    try {
      const { data } = await llmSettingsApi.pull(name)
      if (!data?.success) setLlmError(data?.error || "Failed to pull model")
      setNewModelName("")
      await loadLlms()
    } catch (e: any) {
      setLlmError(e?.message || "Failed to pull model")
    } finally {
      setPulling(false)
    }
  }

  useEffect(() => { check(); loadLlms() }, [])

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

          {/* Local LLMs */}
          <div className="bg-white/[0.03] border border-white/10 rounded-xl p-6">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-white font-semibold">Local LLMs</h2>
              <button onClick={loadLlms} disabled={llmLoading}
                className="flex items-center gap-1.5 text-white/30 hover:text-white text-xs transition-colors">
                <RefreshCw className={`w-3.5 h-3.5 ${llmLoading ? "animate-spin" : ""}`} />
                Refresh
              </button>
            </div>

            {llmLoading ? (
              <div className="flex justify-center py-8"><Loader2 className="animate-spin text-white/20" /></div>
            ) : !llm ? (
              <p className="text-white/30 text-sm">Could not load LLM settings.</p>
            ) : (
              <>
                {/* Provider switch */}
                <div className="flex items-center justify-between py-2 border-b border-white/5 mb-4">
                  <div>
                    <p className="text-white/70 text-sm font-medium">Provider</p>
                    <p className="text-white/30 text-xs mt-0.5">
                      {llm.provider === "claude"
                        ? "Claude API (cloud)"
                        : llm.provider === "gateway"
                        ? "Promon AI Gateway (on-prem)"
                        : llm.provider === "gemini"
                        ? "Google Gemini API (cloud)"
                        : "Ollama (local models)"}
                    </p>
                  </div>
                  <div className="flex bg-white/5 rounded-lg p-1">
                    <button
                      onClick={() => setProvider("ollama")}
                      disabled={llmBusy === "provider"}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                        llm.provider === "ollama" ? "bg-white/80 text-black" : "text-white/40 hover:text-white/70"
                      }`}
                    >
                      <HardDrive className="w-3.5 h-3.5" /> Local
                    </button>
                    <button
                      onClick={() => setProvider("gateway")}
                      disabled={llmBusy === "provider" || !llm.gateway_key_set}
                      title={!llm.gateway_key_set ? "Set GATEWAY_API_KEY in .env first" : ""}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors disabled:opacity-30 ${
                        llm.provider === "gateway" ? "bg-white/80 text-black" : "text-white/40 hover:text-white/70"
                      }`}
                    >
                      <Server className="w-3.5 h-3.5" /> Gateway
                    </button>
                    <button
                      onClick={() => setProvider("claude")}
                      disabled={llmBusy === "provider" || !llm.claude_key_set}
                      title={!llm.claude_key_set ? "Set ANTHROPIC_API_KEY in .env first" : ""}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors disabled:opacity-30 ${
                        llm.provider === "claude" ? "bg-white/80 text-black" : "text-white/40 hover:text-white/70"
                      }`}
                    >
                      <Cloud className="w-3.5 h-3.5" /> Claude
                    </button>
                    <button
                      onClick={() => setProvider("gemini")}
                      disabled={llmBusy === "provider" || !llm.gemini_key_set}
                      title={!llm.gemini_key_set ? "Set GEMINI_API_KEY in .env first" : ""}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors disabled:opacity-30 ${
                        llm.provider === "gemini" ? "bg-white/80 text-black" : "text-white/40 hover:text-white/70"
                      }`}
                    >
                      <Sparkles className="w-3.5 h-3.5" /> Gemini
                    </button>
                  </div>
                </div>

                {llm.provider === "gemini" && (
                  <div className="mb-4 p-3 bg-white/[0.02] border border-white/5 rounded-lg space-y-3">
                    <p className="text-white/30 text-xs">
                      Google Gemini API · key {llm.gemini_key_set ? "configured" : "missing"}
                    </p>
                    <div className="flex items-center gap-4 bg-white/5 rounded-lg px-3 py-2 text-xs">
                      <div>
                        <p className="text-white/25">Total tokens</p>
                        <p className="text-white/70 font-mono">{formatTokens(llm.gemini_usage?.total_tokens || 0)}</p>
                      </div>
                      <div>
                        <p className="text-white/25">Prompt</p>
                        <p className="text-white/70 font-mono">{formatTokens(llm.gemini_usage?.prompt_tokens || 0)}</p>
                      </div>
                      <div>
                        <p className="text-white/25">Completion</p>
                        <p className="text-white/70 font-mono">{formatTokens(llm.gemini_usage?.completion_tokens || 0)}</p>
                      </div>
                      <div>
                        <p className="text-white/25">Calls</p>
                        <p className="text-white/70 font-mono">{llm.gemini_usage?.calls || 0}</p>
                      </div>
                    </div>
                    <div>
                      <label className="text-white/40 text-xs flex items-center gap-1 mb-1">
                        <Type className="w-3 h-3" /> Text model
                      </label>
                      <input
                        value={geminiTextModel}
                        onChange={(e) => setGeminiTextModel(e.target.value)}
                        placeholder="gemini-2.5-flash"
                        className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white/80 text-sm font-mono placeholder:text-white/20 focus:outline-none focus:border-white/30"
                      />
                    </div>
                    <div>
                      <label className="text-white/40 text-xs flex items-center gap-1 mb-1">
                        <Eye className="w-3 h-3" /> Vision model
                      </label>
                      <input
                        value={geminiVisionModel}
                        onChange={(e) => setGeminiVisionModel(e.target.value)}
                        placeholder="gemini-2.5-flash"
                        className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white/80 text-sm font-mono placeholder:text-white/20 focus:outline-none focus:border-white/30"
                      />
                    </div>
                    <button
                      onClick={saveGeminiModels}
                      disabled={llmBusy === "gemini"}
                      className="flex items-center gap-1.5 bg-white/80 hover:bg-white text-black text-xs font-medium px-3 py-2 rounded-lg transition-colors disabled:opacity-30"
                    >
                      {llmBusy === "gemini" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                      Save Gemini models
                    </button>
                  </div>
                )}

                {llm.provider === "gateway" && (
                  <div className="mb-4 p-3 bg-white/[0.02] border border-white/5 rounded-lg space-y-3">
                    <p className="text-white/30 text-xs">
                      {llm.gateway_base_url} · key {llm.gateway_key_set ? "configured" : "missing"}
                    </p>
                    <div>
                      <label className="text-white/40 text-xs flex items-center gap-1 mb-1">
                        <Type className="w-3 h-3" /> Text model
                      </label>
                      <input
                        value={gatewayTextModel}
                        onChange={(e) => setGatewayTextModel(e.target.value)}
                        placeholder="local-qwen25"
                        className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white/80 text-sm font-mono placeholder:text-white/20 focus:outline-none focus:border-white/30"
                      />
                    </div>
                    <div>
                      <label className="text-white/40 text-xs flex items-center gap-1 mb-1">
                        <Eye className="w-3 h-3" /> Vision model
                      </label>
                      <input
                        value={gatewayVisionModel}
                        onChange={(e) => setGatewayVisionModel(e.target.value)}
                        placeholder="local-moondream"
                        className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white/80 text-sm font-mono placeholder:text-white/20 focus:outline-none focus:border-white/30"
                      />
                    </div>
                    <button
                      onClick={saveGatewayModels}
                      disabled={llmBusy === "gateway"}
                      className="flex items-center gap-1.5 bg-white/80 hover:bg-white text-black text-xs font-medium px-3 py-2 rounded-lg transition-colors disabled:opacity-30"
                    >
                      {llmBusy === "gateway" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                      Save gateway models
                    </button>
                  </div>
                )}

                {llm.provider !== "gateway" && llm.provider !== "gemini" && !llm.ollama_reachable && (
                  <p className="text-white/30 text-xs mb-4">
                    Ollama not reachable at {llm.ollama_host} — run <code className="text-white/50">ollama serve</code>
                  </p>
                )}

                {/* Installed models */}
                {llm.provider !== "gateway" && llm.provider !== "gemini" && (
                <>
                <div className="space-y-2 mb-4">
                  {llm.models.length === 0 && llm.ollama_reachable && (
                    <p className="text-white/30 text-xs py-2">No local models installed yet.</p>
                  )}
                  {llm.models.map((m) => {
                    const isText = m.name === llm.text_model
                    const isVision = m.name === llm.vision_model
                    return (
                      <div key={m.name} className="flex items-center justify-between py-2.5 border-b border-white/5 last:border-0">
                        <div className="min-w-0">
                          <p className="text-white/70 text-sm font-mono truncate">{m.name}</p>
                          <p className="text-white/25 text-xs mt-0.5">{formatSize(m.size)}</p>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <button
                            onClick={() => setActiveModel("text_model", m.name)}
                            disabled={llmBusy === "text_model" + m.name}
                            title="Use as text (flow-planning) model"
                            className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium border transition-colors ${
                              isText
                                ? "bg-white/80 text-black border-white/80"
                                : "text-white/40 border-white/10 hover:text-white/70 hover:border-white/30"
                            }`}
                          >
                            <Type className="w-3 h-3" /> Text
                          </button>
                          <button
                            onClick={() => setActiveModel("vision_model", m.name)}
                            disabled={llmBusy === "vision_model" + m.name}
                            title="Use as vision (screen-detection) model"
                            className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium border transition-colors ${
                              isVision
                                ? "bg-white/80 text-black border-white/80"
                                : "text-white/40 border-white/10 hover:text-white/70 hover:border-white/30"
                            }`}
                          >
                            <Eye className="w-3 h-3" /> Vision
                          </button>
                          <button
                            onClick={() => removeModel(m.name)}
                            disabled={llmBusy === "remove" + m.name}
                            title="Remove this local model"
                            className="text-white/20 hover:text-white/60 p-1.5 transition-colors"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </div>

                {/* Add / pull a new model */}
                <div className="flex items-center gap-2">
                  <input
                    value={newModelName}
                    onChange={(e) => setNewModelName(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && !pulling && pullModel()}
                    placeholder="e.g. llama3.1:8b"
                    disabled={pulling}
                    className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white/80 text-sm font-mono placeholder:text-white/20 focus:outline-none focus:border-white/30"
                  />
                  <button
                    onClick={pullModel}
                    disabled={pulling || !newModelName.trim()}
                    className="flex items-center gap-1.5 bg-white/80 hover:bg-white text-black text-xs font-medium px-3 py-2 rounded-lg transition-colors disabled:opacity-30"
                  >
                    {pulling ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                    {pulling ? "Pulling…" : "Pull model"}
                  </button>
                </div>
                {llmError && <p className="text-white/40 text-xs mt-2">{llmError}</p>}
                </>
                )}
              </>
            )}
          </div>

          {/* Quick Setup */}
          <div className="bg-white/[0.03] border border-white/10 rounded-xl p-6">
            <h2 className="text-white font-semibold mb-4">Quick Setup Commands</h2>
            <div className="space-y-2">
              {[
                { label: "Start Ollama LLM",        cmd: "ollama serve" },
                { label: "Load automation-agent model", cmd: "ollama run automation-agent" },
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
