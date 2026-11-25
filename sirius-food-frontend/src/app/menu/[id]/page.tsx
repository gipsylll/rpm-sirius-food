import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getMenuItem, formatPrice } from "@/lib/api";
import { presentDish } from "@/lib/presentation";
import { DishArtwork } from "@/components/DishArtwork";
import { AddToCartButton } from "@/components/AddToCartButton";
type Props = { params: Promise<{ id: string }> };
export const revalidate = 60;
export async function generateMetadata({ params }: Props): Promise<Metadata> {
 let item;
 try {
  item = await getMenuItem((await params).id);
 } catch {
  return { title: "Меню временно недоступно" };
 }
 if (!item) return { title: "Блюдо не найдено" };
 const description = `${item.name} — ${formatPrice(item.price)} в Сириус.Еде`;
 return { title: item.name, description, openGraph: { title: item.name, description } };
}
export default async function MenuItemPage({ params }: Props) {
 const item = await getMenuItem((await params).id);
 if (!item) notFound();
 const art = presentDish(item);
 return <main className="page-shell detail-page"><div className="breadcrumbs"><Link href="/menu">Меню</Link> / {item.name}</div><DishArtwork emoji={art.emoji} tone={art.tone} category={item.category ?? "Меню"} /><h1>{item.name}</h1><p>{formatPrice(item.price)}</p><AddToCartButton available={item.is_available !== false} /></main>;
}
