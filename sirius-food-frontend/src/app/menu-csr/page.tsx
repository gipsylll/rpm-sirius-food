"use client";
import { useEffect, useState } from "react";
import { DishCard } from "@/components/DishCard";
import type { MenuItem } from "@/lib/api";
export default function MenuCSR() {
 const [items, setItems] = useState<MenuItem[] | null>(null);
 const [error, setError] = useState(false);
 useEffect(() => { const controller = new AbortController();
 fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"}/menu/items`, { cache: "no-store", signal: controller.signal }).then(r => { if (!r.ok) throw Error(); return r.json(); }).then(setItems).catch(e => { if (e.name !== "AbortError") setError(true); });
 return () => controller.abort(); }, []);
 return <main className="page-shell"><h1>Меню CSR</h1>{error ? <p>Не удалось загрузить меню</p> : items === null ? <p>Загрузка...</p> : <div className="dish-grid">{items.map(item => <DishCard key={item.id} item={item}/>)}</div>}</main>;
}
