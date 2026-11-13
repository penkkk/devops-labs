# 13. Kubernetes: deploy, probes и восстановление

**Время:** 5–8 часов. **Перед началом:** Docker и диагностика из предыдущих лаб.

## Цель

Запустить уже знакомый API в учебном Kubernetes и объяснить, что происходит
при неготовности Pod, падении процесса и неудачном обновлении.

## Подготовка

Используй single-node **kind** на `mon` или отдельной учебной Linux-машине.
Managed cluster, публичный ingress и LoadBalancer не требуются. На маленькой VM
останови Loki/Grafana и другие необязательные компоненты, проверь доступную RAM
и диск. Если ресурсов не хватает, перенеси эту лабу, а не отключай лимиты ОС.

Установи kind и kubectl по официальным инструкциям; запиши версии. Создай кластер
с отдельным именем `devops-lab`, API server на loopback, namespace `ops-lab`.
Не меняй context рабочего кластера: проверяй текущий context перед командами.
Скопируй свой образ на узел kind через registry или `docker save/load` и
`kind load docker-image`. Учебный локальный tag должен быть явным, не `latest`.

## Задания

1. Напиши Deployment с двумя replicas, непривилегированным пользователем,
   requests/limits CPU и RAM. Передай `APP_HOST=0.0.0.0`, порт и версию через
   ConfigMap/env. Проверь imagePullPolicy для образа, загруженного локально.
2. Для данных используй **копию** `items.json` в `emptyDir`, которую initContainer
   заполняет из образа или ConfigMap. Приложение читает `/data`. Настрой права для
   UID приложения, чтобы в этом учебном каталоге можно было создать `not-ready`.
   Объясни, почему emptyDir не является постоянным хранилищем и не подходит для базы.
3. Добавь startupProbe, readinessProbe на `/readyz` и livenessProbe на `/healthz`.
   Объясни выбранные initial delays, periods и failure thresholds. Не проверяй
   внешнюю зависимость через liveness, если её сбой не означает зависание процесса.
4. Создай ClusterIP Service, проверь selectors и EndpointSlice. Получи доступ через
   `kubectl port-forward` на loopback узла, затем SSH-туннель со своего компьютера.
   Port-forward к Service выбирает один Pod и не доказывает балансировку.
   Для проверки обоих replicas используй временный клиентский Pod внутри кластера.
5. Удали один Pod, проверь создание нового и доступность Service из клиентского Pod.
   Сравни restart контейнера и замену Pod: UID, restartCount и содержимое emptyDir.
6. В **одном** Pod создай `/data/not-ready`. Проверь readiness=false, исключение
   из готовых endpoints и сохранение liveness. Удали файл, докажи возвращение в endpoints.
7. Обнови образ на `v2` с другой `APP_VERSION`, настрой RollingUpdate с явными
   maxSurge/maxUnavailable. Проверь rollout status, версию через `/`, события и imageID.
8. Введи плохой image tag, затем отдельно неверный `DATA_DIR`. Разбери
   ImagePullBackOff и живой, но неготовый Pod. Выполни rollout undo, проверь версию,
   readiness и Service. Неудачный rollout сам по себе не гарантирует автоматического отката.
9. Опиши ConfigMap и Secret; создай Secret только с фиктивным значением. Объясни,
   почему base64 не является шифрованием. Настоящие ключи в manifests не добавляй.

## Инциденты для самостоятельной диагностики

| Симптом | Что намеренно изменить | Где искать доказательства |
|---|---|---|
| Service без endpoints | Несовпадающий selector | labels Pod, Service, EndpointSlice |
| ImagePullBackOff | Несуществующий tag | describe/events, наличие образа на kind node |
| CrashLoopBackOff | `APP_PORT=oops` | logs и logs --previous, termination reason |
| Pod Running, но не Ready | Файл `not-ready` или неверный DATA_DIR | Probe events, `/healthz` против `/readyz` |
| Pod Pending | requests CPU заведомо выше capacity учебного узла | Scheduler events; не создавай реальную нагрузку |

После каждого случая верни рабочий manifest. Для Pending достаточно одного
непланируемого Pod, не нужно создавать десятки replicas.

## Приёмка и что сдать

- Manifests и команды развёртывания в своём namespace, версии и схема сети.
- Два Ready Pod, Service endpoints, доказанный recovery после удаления Pod.
- Readiness исключает один Pod из трафика без liveness restart.
- Успешное обновление и откат подтверждены версией и событиями; пять расследований.
- Зафиксирована потеря emptyDir при замене Pod. Для постоянных данных описан PVC,
  но учебный single-node storage не выдан за отказоустойчивую базу.

Очистка: удалить namespace и только кластер `devops-lab` через kind. Проверить
созданные Docker-объекты; вернуть остановленный мониторинг. Не удалять остальные
Docker networks/volumes и чужие Kubernetes contexts.

## Контрольные вопросы

1. Какие задачи решают Pod, Deployment и Service?
2. Что случится при readiness failure, liveness failure и завершении main process?
3. Почему два replicas на одном узле не защищают от падения VM?
4. Чем requests отличаются от limits и от фактически потребляемых ресурсов?
5. Что приложение не получает автоматически только от переноса в Kubernetes?

Документация: [kind quick start](https://kind.sigs.k8s.io/docs/user/quick-start/),
[Kubernetes tutorial](https://kubernetes.io/docs/tutorials/hello-minikube/)
для понятий Deployment, Service и kubectl; установка minikube для этой лабы не нужна.
