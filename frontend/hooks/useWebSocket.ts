"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import { WSMessage } from "@/types"

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000"

export function useExecutionWebSocket(execId: string | null) {
  const ws = useRef<WebSocket | null>(null)
  const [messages, setMessages] = useState<WSMessage[]>([])
  const [connected, setConnected] = useState(false)
  const [status, setStatus] = useState<string>("pending")
  const pingInterval = useRef<NodeJS.Timeout | null>(null)

  const connect = useCallback(() => {
    if (!execId) return
    const url = `${WS_URL}/api/execution/ws/${execId}`

    try {
      const socket = new WebSocket(url)
      ws.current = socket

      socket.onopen = () => {
        setConnected(true)
        pingInterval.current = setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) socket.send("ping")
        }, 25000)
      }

      socket.onmessage = (event) => {
        if (event.data === "ping") { socket.send("pong"); return }
        if (event.data === "pong") return
        try {
          const msg: WSMessage = JSON.parse(event.data)
          setMessages((prev) => [...prev, msg])
          if (msg.type === "status") {
            setStatus((msg.data as { status: string }).status)
          }
          if (msg.type === "complete") {
            setStatus("done")
          }
        } catch {}
      }

      socket.onclose = () => {
        setConnected(false)
        if (pingInterval.current) clearInterval(pingInterval.current)
      }

      socket.onerror = () => {
        setConnected(false)
      }
    } catch {}
  }, [execId])

  useEffect(() => {
    connect()
    return () => {
      ws.current?.close()
      if (pingInterval.current) clearInterval(pingInterval.current)
    }
  }, [connect])

  return { messages, connected, status }
}
