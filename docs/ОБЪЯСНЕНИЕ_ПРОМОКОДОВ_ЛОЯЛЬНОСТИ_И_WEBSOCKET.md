# Что работает в треках промокодов, лояльности и WebSocket

Этот документ объясняет, какие функции реализованы в проекте и как их проверить.

## 1. Промокоды

Администратор может создать промокод через `POST /promocodes` или `POST /admin/promocodes`.

```json
{
  "code": "STUDENT10",
  "discount_type": "percent",
  "discount_value": 10,
  "max_uses": 100,
  "min_order_amount": 200
}
```

Поддерживаются два типа скидки:

- `percent` — процентная скидка от суммы заказа;
- `fixed` — фиксированная скидка в рублях.

Промокод проверяется по активности, сроку действия, минимальной сумме заказа и лимиту применений. Код автоматически приводится к верхнему регистру. Один пользователь не может повторно применить один и тот же код. Для защиты от гонок промокод блокируется в PostgreSQL через `SELECT ... FOR UPDATE`.

Администратор может:

- `GET /promocodes` — посмотреть список кодов;
- `DELETE /promocodes/{promo_id}` — деактивировать код.

Celery Beat каждую минуту запускает задачу деактивации просроченных промокодов.

## 2. Оформление заказа со скидкой и баллами

`POST /orders/create` принимает дополнительные поля:

```json
{
  "item_id": 1,
  "quantity": 2,
  "promo_code": "student10",
  "loyalty_points": 50
}
```

При оформлении заказа система:

1. Находит пользователя и блюдо.
2. Проверяет доступность блюда и баланс пользователя.
3. Нормализует промокод.
4. Проверяет срок, лимит, минимальную сумму и повторное использование.
5. Рассчитывает процентную или фиксированную скидку.
6. Проверяет, что баллами оплачивается не больше 50% суммы после скидки.
7. Проверяет остаток баллов пользователя.
8. Списывает деньги, баллы и фиксирует использование промокода в одной транзакции.
9. Записывает финансовые поля заказа:
   - исходную сумму;
   - сумму скидки;
   - списанные баллы;
   - итоговую сумму;
   - применённый промокод.
10. Добавляет событие `order.paid` в transactional outbox.

Денежные значения хранятся в PostgreSQL как `NUMERIC(12,2)`, поэтому расчёты не используют `Float`.

## 3. Лояльность

Для пользователя создаётся `LoyaltyAccount`. В аккаунте хранятся баланс баллов, общее количество заработанных баллов и уровень.

Уровни начисления:

| Уровень | Накоплено баллов | Начисление с оплаченного заказа |
|---|---:|---:|
| Bronze | до 1 000 | 3% |
| Silver | от 1 000 до 5 000 | 5% |
| Gold | от 5 000 | 7% |

После события `order.paid` consumer лояльности:

- создаёт аккаунт при необходимости;
- рассчитывает начисление по уровню;
- увеличивает баланс и `total_earned`;
- повышает уровень при достижении порога;
- записывает транзакцию `earn`.

Ключ `earn_order_{order_id}` не позволяет повторно начислить баллы при повторной доставке события.

## 4. Отмена заказа и Saga-компенсации

При отмене заказа `OrderService` публикует событие `order.cancelled`.

Consumer компенсаций выполняет идемпотентные действия:

- возвращает списанные баллы с ключом `refund_order_{order_id}`;
- отзывает начисленные за заказ баллы с ключом `revoke_earn_order_{order_id}`;
- уменьшает `current_uses` промокода;
- удаляет использование промокода, чтобы его можно было применить снова;
- записывает `PromoCompensation` с ключом `restore_promo_order_{order_id}`.

Повторная доставка `order.cancelled` не создаёт повторных возвратов или повторного восстановления промокода.

## 5. Изменение статуса доставки

Для курьера или администратора доступен endpoint:

```text
PATCH /delivery/{delivery_id}/status
```

Тело запроса:

```json
{"status": "in_transit"}
```

Поддерживается последовательность:

```text
assigned → picked_up → in_transit → arrived → delivered
```

Статус сохраняется в PostgreSQL, меняет статус связанного заказа и публикуется в Redis Pub/Sub.

## 6. WebSocket-трекинг заказа

Endpoint:

```text
/ws/orders/{order_id}?token=<ACCESS_JWT>
```

При подключении сервер:

1. Проверяет access JWT.
2. Проверяет, что заказ принадлежит пользователю из токена.
3. Отправляет актуальный snapshot.
4. Добавляет соединение в локальный менеджер реплики.

Пример snapshot:

```json
{
  "type": "snapshot",
  "order_id": 42,
  "status": "in_transit",
  "delivery_status": "in_transit",
  "history": [
    {"status": "in_transit", "timestamp": "2026-11-25T12:00:00Z"}
  ]
}
```

При изменении статуса клиент получает событие:

```json
{
  "type": "status_update",
  "order_id": 42,
  "status": "delivered",
  "delivery_status": "delivered",
  "timestamp": "2026-11-25T12:05:00Z"
}
```

Сервер периодически отправляет heartbeat:

```json
{"type": "ping", "timestamp": "2026-11-25T12:00:20Z"}
```

Клиент отвечает:

```json
{"type": "pong"}
```

Все реплики API публикуют изменения в канал Redis `order_updates`. Каждая реплика подписывается на этот канал и отправляет событие своим подключённым клиентам. Поэтому WebSocket получает обновление независимо от того, какая реплика обработала запрос изменения статуса.

При переподключении Redis-события не восстанавливаются из истории. Вместо этого сервер снова читает текущий статус из PostgreSQL и отправляет snapshot.

## 7. Демонстрация в Next.js

Страница трекинга находится по адресу:

```text
/orders/{order_id}/track?token=<ACCESS_JWT>
```

Страница:

- берёт JWT из query-параметра или `localStorage.access_token`;
- открывает WebSocket;
- показывает текущий статус;
- отображает историю переходов;
- показывает состояние подключения;
- отвечает на heartbeat;
- автоматически переподключается;
- выводит ошибку при недействительном токене или недоступном WebSocket.

URL WebSocket задаётся в `sirius-food-frontend/.env.local`:

```env
NEXT_PUBLIC_WS_URL=ws://127.0.0.1:8000
```

## 8. Где находится реализация

- ORM-модели: `app/models.py`;
- схемы запросов: `app/schemas.py`;
- расчёт заказа: `app/modules/orders/service.py`;
- работа с промокодами и финансовыми полями: `app/modules/orders/repository.py`;
- административные endpoints промокодов: `app/modules/promos/router.py`;
- обработка Saga-событий: `app/events/common.py`;
- Redis Pub/Sub и менеджер WebSocket: `app/modules/orders/websocket.py`;
- WebSocket endpoint и lifespan: `app/main.py`;
- статус доставки: `app/modules/delivery/service.py` и `app/modules/delivery/router.py`;
- миграция: `alembic/versions/004_promos_loyalty.py`;
- страница Next.js: `sirius-food-frontend/src/app/orders/[order_id]/track/page.tsx`.

## 9. Проверка

Основные проверки:

```bash
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked pytest -q
npm --prefix sirius-food-frontend run build
```

Нагрузочные сценарии:

```bash
uv run --locked locust -f locustfile_promos.py --users 1000 --spawn-rate 100
WS_TOKEN=<ACCESS_JWT> uv run --locked python scripts/load_websockets.py
```

Полное архитектурное обоснование находится в [ADR](adr/001-order-tracking-and-loyalty.md).
