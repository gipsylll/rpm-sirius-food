"use client";
export default function ErrorPage({ reset }: { error: Error; reset: () => void }) { return <main className="page-shell"><h1>Не удалось загрузить меню</h1><p>Проверьте доступность сервера.</p><button onClick={reset}>Попробовать снова</button></main>; }
