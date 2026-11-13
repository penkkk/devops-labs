# 08. Docker и Compose: перенос сервиса без потери наблюдаемости

**Время:** 4–6 часов. **Перед началом:** лабы 02–07, рабочий backup.

## Цель

Упаковать API, запустить API и Nginx через Compose, сохранить данные при пересоздании
контейнеров и воспроизвести сетевые ошибки внутри контейнерного окружения.

## Подготовка и переход

Установи Docker Engine и Compose plugin по официальной инструкции. Команды курса
используют `docker compose`. Доступ к Docker socket даёт широкие права на хост:
не выдавай его пользователю API и не монтируй socket внутрь приложения.

Сначала собери образ и сохрани native-конфиги. Только затем останови и отключи
`ops-demo.service` и native Nginx. Подготовь обратный переход на них. Для этой лабы
используй закрытую схему публикации:

```text
host 127.0.0.1:8080 → container api:8080   # только для scrape через SSH-туннель
host 127.0.0.1:8088 → container proxy:80
host 127.0.0.1:8443 → container proxy:443
container proxy → http://api:8080         # Compose DNS, не localhost
```

На `mon` scrape API идёт через туннель `18080 → app:8080`. Браузер использует
SSH-туннель к 8443. Не полагайся только на UFW при публикации Docker-портов:
Docker создаёт собственные правила, и опубликованный порт может обходить обычную
цепочку UFW. Явно указывай host bind и проверяй доступ с другого узла.

## Задания

1. Напиши Dockerfile для `ops-demo`: базовый Python 3.12+ образ с закреплённым
   digest, рабочий каталог, только необходимые файлы, непривилегированный UID,
   exec-form команды запуска. Не устанавливай лишние пакеты ради healthcheck:
   в образе уже есть Python и `urllib`.
2. Добавь `.dockerignore` для Git, `.env`, приватных ключей, архивов и временных
   файлов. Проверь `docker history` и содержимое образа на отсутствие секретов.
3. Напиши Compose для `api` и `proxy` на общей сети. API внутри контейнера должен
   слушать `0.0.0.0:8080`. Nginx обращается по имени `api`, а не по меняющемуся IP.
   Подключи конфиг Nginx, учебный сертификат и ключ как read-only mounts.
4. Подключи `/var/lib/ops-demo` как read-only bind mount в `/data`; задай `DATA_DIR`.
   Проверь числовой UID/GID и чтение файла непривилегированным процессом. Не решай
   ошибки доступа через root или `chmod 777`. API только читает данные, поэтому
   read-only mount достаточно; данные изменяет администратор на хосте.
5. Перенеси TLS и request ID из лабы 06. Учти новые порты и адреса, видимые Nginx
   после Docker NAT: старые `allow` не копируй без проверки. Закрытость обеспечь
   loopback-публикацией и проверь снаружи. Направь access/error logs Nginx в stdout/stderr.
6. Добавь healthcheck через `/readyz`, ограничение CPU/RAM и restart policy.
   Проверь фактические лимиты через inspect/stats. Разбери startup dependency
   `depends_on` с условием health и её поведение после запуска.
7. Собери `v1`, затем `v2` с другой `APP_VERSION`. Пересоздай API, докажи сохранность
   `/items`, выполни откат на прежний digest. После recreate проверь DNS-кеш upstream
   в Nginx: настрой повторное разрешение имени для своей версии либо включи reload
   proxy в процедуру обновления. Healthcheck сам по себе не запускает рестарт
   контейнера — проверь это через файл `not-ready`.

## Инциденты

- API слушает loopback **внутри** контейнера: локальный healthcheck может пройти,
  но Nginx из соседнего контейнера не достучится.
- В upstream написан `localhost`: выясни, чей это localhost.
- Неправильный путь или UID у bind mount: healthcheck/readyz=503, лог `PermissionError`
  или `FileNotFoundError`.
- Запрошен занятый host-port: контейнер не стартует; сравни ошибку Docker и `ss`.
- Healthcheck=unhealthy при живом процессе: докажи отличие от exited.

## Приёмка и что сдать

- Dockerfile, `.dockerignore`, Compose и команда запуска с нуля проходят
  `docker compose config` и проверку API/TLS.
- Изменения данных пережили recreate; образ и mount разделены, старый digest сохранён.
- Dashboard и алерты продолжают работать. Перезапуск API виден в counter.
- Логи API и proxy доступны; API и Nginx workers работают без root, порты закрыты
  от внешнего доступа. Права master-процесса Nginx объяснены отдельно.
- Пять расследований и инструкция возврата к native systemd без конфликта портов.

Очистка: `docker compose down` в своём проекте после сохранения данных. Не выполняй
глобальный `docker system prune` и не удаляй чужие volumes. Ключ `down -v` удаляет
named volumes проекта, поэтому не используй его без проверенного backup.

## Контрольные вопросы

1. Где живут writable layer, bind mount и named volume? Что переживает recreate?
2. Чем image tag отличается от digest?
3. Какие гарантии дают healthcheck, restart policy и `depends_on`, а каких не дают?
4. Почему DNS-имя сервиса надёжнее IP контейнера, и как proxy узнаёт новый IP после recreate?

Документация: [Compose quickstart](https://docs.docker.com/compose/gettingstarted/),
[Docker firewall](https://docs.docker.com/engine/network/packet-filtering-firewalls/).
