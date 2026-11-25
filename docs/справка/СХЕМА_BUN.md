flowchart TD
    %% Стили узлов
    classDef loopStep fill:#1E293B,stroke:#475569,stroke-width:2px,color:#F8FAFC;
    classDef bottleneck fill:#7F1D1D,stroke:#DC2626,stroke-width:2px,color:#FEF2F2;
    classDef decision fill:#334155,stroke:#94A3B8,stroke-width:2px,color:#FFFFFF;
    classDef kernel fill:#0F172A,stroke:#38BDF8,stroke-width:2px,color:#E0F2FE;

    Start([СТАРТ ИТЕРАЦИИ ЦИКЛА / ТИКА]) --> SnapTime["1. Снятие метки времени: clock_gettime<br/>Запись в loop_time (Node.js) или cache_now (Bun)"]:::loopStep

    %% ТОРМОЗ 1: Кеширование времени
    SnapTime --> Delay1["⚠️ ЗАДЕРЖКА 1: Заморозка времени<br/>Время внутри тика НЕ обновляется!<br/>Таймеры, чей срок наступил во время тика,<br/>не увидятся до следующего витка"]:::bottleneck
    Delay1 --> TimersPhase["2. ФАЗА ТАЙМЕРОВ: Проверка корня Min-Heap"]:::loopStep

    TimersPhase --> CheckHeap{"Корень Min-Heap<br/>T_min &le; loop_time ?"}:::decision

    %% Ветка исполнения таймера
    CheckHeap -- "Да: дедлайн наступил" --> ExtractTimer["Извлечение T_min из кучи<br/>Вызов колбэка: fn.apply()"]:::loopStep
    ExtractTimer --> ExecSync["Выполнение тела JS-колбэка<br/>в стеке вызовов (Call Stack)"]:::loopStep

    %% ТОРМОЗ 2: Блокировка синхронным кодом
    ExecSync --> Delay2["⚠️ ЗАДЕРЖКА 2: Синхронная блокировка CPU<br/>(Длинный цикл while, JSON.parse, крипта)<br/>Пока стек занят, цикл событий ЗАМЕРТВО СТОИТ.<br/>Никакие другие таймеры и I/O не сдвинутся!"]:::bottleneck
    Delay2 --> DrainMicro["3. Очистка очереди микротасок<br/>(process.nextTick, Promise.then, queueMicrotask)"]:::loopStep

    %% ТОРМОЗ 3: Голодание микротасок
    DrainMicro --> Delay3["⚠️ ЗАДЕРЖКА 3: Microtask Starvation (Голодание)<br/>Микротаски порождают новые микротаски?<br/>Цикл не выйдет из очистки, пока очередь не пуста.<br/>Макро-таймеры ждут бесконечно!"]:::bottleneck
    Delay3 --> CheckHeap

    %% Переход к I/O
    CheckHeap -- "Нет: готовых таймеров нет" --> CalcSleep["4. Расчет времени сна для фазы Poll<br/>Формула: timeout = max(0, T_min - loop_time)"]:::loopStep

    CalcSleep --> CheckImmediate{"Есть ли задачи<br/>setImmediate (Node)<br/>или готовый I/O?"}:::decision

    CheckImmediate -- "Да" --> ZeroSleep["timeout = 0 мс (без сна в ядре)"]:::loopStep
    CheckImmediate -- "Нет" --> TimeoutSleep["timeout = разница до T_min"]:::loopStep

    ZeroSleep --> PollPhase
    TimeoutSleep --> PollPhase

    PollPhase["5. ФАЗА POLL: Ожидание в ядре ОС<br/>epoll_wait (Node) / io_uring_enter (Bun)"]:::kernel

    %% ТОРМОЗ 4: Погрешность планировщика ОС
    PollPhase --> Delay4["⚠️ ЗАДЕРЖКА 4: Квантование ядра ОС<br/>• CONFIG_HZ (шаг таймера 1–4 мс)<br/>• Timer Slack (ядро группирует пробуждения)<br/>Поток просыпается позже, чем запрошено!"]:::bottleneck
    Delay4 --> WakeUp["Пробуждение потока из сна ядра"]:::loopStep

    WakeUp --> ProcessIO["6. Обработка проснувшихся сетевых событий<br/>(Вычитка сокетов, парсинг HTTP, TLS handshake)"]:::loopStep

    %% ТОРМОЗ 5: I/O лавина
    ProcessIO --> Delay5["⚠️ ЗАДЕРЖКА 5: Лавина сетевых событий (I/O Flood)<br/>Пришло 5000 сетевых пакетов?<br/>Цикл будет разбирать каждый сокет по очереди.<br/>Возврат к фазе таймеров откладывается!"]:::bottleneck
    Delay5 --> PostPollTime["7. Обновление метки времени после фазы Poll"]:::loopStep

    PostPollTime --> CheckPhase["8. ФАЗЫ CHECK & CLOSE<br/>setImmediate, socket.on('close')"]:::loopStep

    CheckPhase --> EndIteration([ЗАВЕРШЕНИЕ ТИКА / ПЕРЕХОД К СЛЕДУЮЩЕМУ])
    EndIteration --> Start