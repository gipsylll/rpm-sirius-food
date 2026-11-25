"use client";

export default function MenuItemError({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="page-shell">
      <h1>Не удалось загрузить блюдо</h1>
      <p>Проверьте доступность сервера меню.</p>
      <button onClick={reset}>Попробовать снова</button>
    </main>
  );
}
