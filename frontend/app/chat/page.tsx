"use client"

import { useState, useRef, useEffect } from "react"
import { chatApi, llmSettingsApi } from "@/lib/api"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import { Send, Loader2, Bot, User, HardDrive, Server, Cloud, Sparkles } from "lucide-react"
import { cn } from "@/lib/utils"

type Message = { role: "user" | "assistant"; content: string }
type Provider = "ollama" | "claude" | "gateway" | "gemini"

const PROVIDERS: { key: Provider; label: string; icon: typeof HardDrive }[] = [
  { key: "ollama",  label: "Local",   icon: HardDrive },
  { key: "gateway", label: "Gateway", icon: Server },
  { key: "gemini",  label: "Gemini",  icon: Sparkles },
  { key: "claude",  label: "Claude",  icon: Cloud },
]

export default function ChatPage() {
  const bottomRef = useRef<HTMLDivElement>(null)

  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: "Hi! Ask me anything." },
  ])
  const [input, setInput]     = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState("")
  const [modelTag, setModelTag] = useState<string | null>(null)
  const [provider, setProvider] = useState<Provider>("ollama")
  const [keysSet, setKeysSet]   = useState<Record<Provider, boolean>>({
    ollama: true, claude: false, gateway: false, gemini: false,
  })

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, loading])

  useEffect(() => {
    llmSettingsApi.list().then(({ data }) => {
      setKeysSet({
        ollama:  true,
        claude:  !!data.claude_key_set,
        gateway: !!data.gateway_key_set,
        gemini:  !!data.gemini_key_set,
      })
      setProvider(data.provider || "ollama")
    }).catch(() => {})
  }, [])

  const send = async () => {
    const text = input.trim()
    if (!text || loading) return

    const next = [...messages, { role: "user" as const, content: text }]
    setMessages(next)
    setInput("")
    setLoading(true)
    setError("")

    try {
      const { data } = await chatApi.send(next, provider)
      setMessages(prev => [...prev, { role: "assistant", content: data.reply }])
      setModelTag(`${data.provider} · ${data.model}`)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || "Chat request failed")
    } finally {
      setLoading(false)
    }
  }

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="flex min-h-screen bg-black">
      <Sidebar />
      <div className="flex-1 flex flex-col h-screen">
        <Header title="Chat Agent" />

        {/* Provider switch — chat-only, does not affect flow execution settings */}
        <div className="border-b border-white/10 px-6 py-3 flex items-center gap-3">
          <span className="text-white/30 text-xs">Model:</span>
          <div className="flex bg-white/5 rounded-lg p-1">
            {PROVIDERS.map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setProvider(key)}
                disabled={!keysSet[key]}
                title={!keysSet[key] ? `Set up ${label} in Settings first` : ""}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors disabled:opacity-30",
                  provider === key ? "bg-white/80 text-black" : "text-white/40 hover:text-white/70"
                )}
              >
                <Icon className="w-3.5 h-3.5" /> {label}
              </button>
            ))}
          </div>
          {modelTag && <span className="text-white/25 text-xs ml-auto">via {modelTag}</span>}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
          {messages.map((msg, i) => (
            <div key={i} className={cn("flex gap-3", msg.role === "user" ? "justify-end" : "justify-start")}>
              {msg.role === "assistant" && (
                <div className="w-7 h-7 rounded-full bg-white/10 flex items-center justify-center shrink-0 mt-0.5">
                  <Bot className="w-4 h-4 text-white/60" />
                </div>
              )}

              <div className={cn(
                "max-w-2xl rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap",
                msg.role === "user"
                  ? "bg-white text-black rounded-br-sm"
                  : "bg-white/5 border border-white/10 text-white/80 rounded-bl-sm"
              )}>
                {msg.content}
              </div>

              {msg.role === "user" && (
                <div className="w-7 h-7 rounded-full bg-white/10 flex items-center justify-center shrink-0 mt-0.5">
                  <User className="w-4 h-4 text-white/60" />
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div className="flex gap-3 justify-start">
              <div className="w-7 h-7 rounded-full bg-white/10 flex items-center justify-center shrink-0">
                <Bot className="w-4 h-4 text-white/60" />
              </div>
              <div className="bg-white/5 border border-white/10 rounded-2xl rounded-bl-sm px-4 py-3">
                <Loader2 className="w-4 h-4 animate-spin text-white/40" />
              </div>
            </div>
          )}

          {error && (
            <div className="text-center text-red-400/70 text-xs">{error}</div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input bar */}
        <div className="border-t border-white/10 px-6 py-4">
          <div className="flex gap-3 items-end">
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={onKey}
              rows={3}
              disabled={loading}
              placeholder="Type a message..."
              className="flex-1 bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white text-sm
                         placeholder-white/20 focus:outline-none focus:border-white/25 transition-colors
                         resize-none disabled:opacity-50"
            />
            <button
              onClick={send}
              disabled={loading || !input.trim()}
              className="flex items-center justify-center w-10 h-10 bg-white text-black rounded-xl
                         hover:bg-white/90 transition-all disabled:opacity-30 shrink-0 mb-0.5"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </div>
          <p className="text-white/20 text-xs mt-2 pl-1">Enter to send · Shift+Enter for new line</p>
        </div>
      </div>
    </div>
  )
}
