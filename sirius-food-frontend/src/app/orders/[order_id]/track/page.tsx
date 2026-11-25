"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

const statuses = ["processing", "assigned", "picked_up", "in_transit", "arrived", "delivered"];

type Event = { type: string; status?: string; delivery_status?: string; timestamp?: string; history?: { status: string; timestamp: string }[]; };

export default function TrackOrderPage() {
  const params = useParams<{ order_id: string }>();
  const orderId = params.order_id;
  const [event, setEvent] = useState<Event | null>(null);
  const [history, setHistory] = useState<{ status: string; timestamp?: string }[]>([]);
  const [connection, setConnection] = useState("connecting");
  const [error, setError] = useState("");
  const wsUrl = useMemo(() => process.env.NEXT_PUBLIC_WS_URL ?? "ws://127.0.0.1:8000", []);

  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("token") ?? localStorage.getItem("access_token");
    if (!token) { setError("Для трекинга нужен JWT-токен"); setConnection("error"); return; }
    let socket: WebSocket;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout>;
    const connect = () => {
      setConnection(retry ? "reconnecting" : "connecting");
      socket = new WebSocket(`${wsUrl}/ws/orders/${orderId}?token=${encodeURIComponent(token)}`);
      socket.onopen = () => { retry = 0; setConnection("connected"); setError(""); };
      socket.onmessage = (message) => {
        const data = JSON.parse(message.data) as Event;
        if (data.type === "ping") { socket.send(JSON.stringify({ type: "pong" })); return; }
        setEvent(data);
        if (data.history) setHistory(data.history);
        if (data.status && data.type !== "snapshot") {
          setHistory((previous) => previous.length && previous[previous.length - 1]?.status === data.status
            ? previous
            : [...previous, { status: data.status as string, timestamp: data.timestamp }]);
        }
      };
      socket.onerror = () => { setError("WebSocket недоступен или токен отклонён"); setConnection("error"); };
      socket.onclose = (close) => {
        if (close.code === 1008) { setError("Нет доступа к этому заказу или JWT недействителен"); setConnection("error"); return; }
        setConnection("reconnecting"); timer = setTimeout(() => { retry += 1; connect(); }, Math.min(1000 * 2 ** retry, 10000));
      };
    };
    connect();
    return () => { clearTimeout(timer); socket?.close(); };
  }, [orderId, wsUrl]);

  const current = event?.delivery_status ?? event?.status ?? "unknown";
  return <main style={{ maxWidth: 720, margin: "40px auto", padding: 24, fontFamily: "system-ui" }}>
    <h1>Трекинг заказа #{orderId}</h1>
    <p>Подключение: <strong>{connection}</strong></p>
    {error && <p role="alert" style={{ color: "#b91c1c" }}>{error}</p>}
    <section style={{ padding: 24, borderRadius: 16, background: "#f1f5f9" }}>
      <div style={{ fontSize: 32, fontWeight: 700 }}>{current}</div>
      <p>Последнее обновление: {event?.timestamp ?? "ожидание snapshot"}</p>
    </section>
    <h2>История переходов</h2>
    <ol>{history.map((item, index) => <li key={`${item.status}-${index}`}><strong>{item.status}</strong> {item.timestamp && `— ${item.timestamp}`}</li>)}</ol>
    <p style={{ color: "#64748b" }}>Этапы: {statuses.join(" → ")}</p>
  </main>;
}
