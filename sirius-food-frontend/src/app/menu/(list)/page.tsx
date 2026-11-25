import type { Metadata } from "next";
import { getMenuItems } from "@/lib/api";
import { DishCard } from "@/components/DishCard";
export const revalidate = 60;
export const metadata: Metadata = { title: "Меню", description: "Меню Сириус.Еды" };
export default async function MenuPage() {
  const items = await getMenuItems();
  return <main className="page-shell"><h1>Меню</h1>{items.length ? <div className="dish-grid">{items.map(item => <DishCard key={item.id} item={item} />)}</div> : <p>В меню пока нет блюд.</p>}</main>;
}
