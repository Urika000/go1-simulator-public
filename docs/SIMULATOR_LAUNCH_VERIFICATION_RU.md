# Проверка инструкции запуска — 15.11.2026

Исходный HEAD: `24143b4` (публичный checkout). Изменение runtime ограничено
флагом `--sim-only` в существующем `run_local.py`. Judge, физика, API,
participant_runtime и Compose не менялись. Существующий посторонний untracked
`docs/ROS2_PUBLIC_API_VERIFICATION.md` не входит в этот результат.

## Окружение и образ

Ubuntu 22.04.5 LTS, amd64, Python 3.10.12, Git 2.34.1,
Docker Engine 29.9.3, Compose 5.7.0; без обязательного NVIDIA GPU.
Реальный `docker pull registry.cookcloud.ru/go1-hackathon-remote-stage/go1-sim:v1.0`
успешен; manifest digest:
`sha256:c79ddbece6cc7d00f114a9a9a09be0bae061ebb35ca722bcbe51bf75fce1b2e3`.
`docker image inspect` подтвердил RepoDigest и linux/amd64; точное сравнение
через `grep -Fx` — PASS. Интерактивный login новой учётной записью не выполнялся:
pull использовал существующие настройки доступа.

Процедура установки Docker и имена пакетов сверены с
[официальным руководством Docker](https://docs.docker.com/engine/install/ubuntu/)
и [настройкой прав](https://docs.docker.com/engine/install/linux-postinstall/).
Системная установка пакетов и групп не выполнялась на уже настроенном хосте.
`docker version`, `docker info`, `docker compose version`, `git --version`,
`python3 --version`, `docker run --rm hello-world` — PASS.

GitHub действительно доступен: выполнены clone в отдельный `/tmp` и
`git pull --ff-only origin main` (Already up to date). Рабочий checkout не обновлялся.
Git push и Docker push не выполнялись.

## Выполненные команды проверок

Из корня публичного checkout:

```bash
python3 run_local.py --help
python3 -m py_compile run_local.py participant_runtime.py
SIM_IMAGE=registry.cookcloud.ru/go1-hackathon-remote-stage/go1-sim:v1.0 docker compose config --quiet
SIM_IMAGE=registry.cookcloud.ru/go1-hackathon-remote-stage/go1-sim:v1.0 docker compose -f docker-compose.yml -f docker-compose.headless.yml config --quiet
SIM_IMAGE=registry.cookcloud.ru/go1-hackathon-remote-stage/go1-sim:v1.0 python3 -B tests/local_launch/runtime_check.py
python3 -B tests/check_public_tree.py
SIM_IMAGE=registry.cookcloud.ru/go1-hackathon-remote-stage/go1-sim:v1.0 PARTICIPANT_IMAGE=go1-participant:example python3 -B tests/local_launch/smoke.py /tmp/go1-guide-pair-20261115
SMOKE_CASE=T4 SIM_IMAGE=registry.cookcloud.ru/go1-hackathon-remote-stage/go1-sim:v1.0 PARTICIPANT_IMAGE=go1-participant:example python3 -B tests/local_launch/smoke.py /tmp/go1-guide-pair-t4-20261115
SMOKE_CASE=T5 SIM_IMAGE=registry.cookcloud.ru/go1-hackathon-remote-stage/go1-sim:v1.0 PARTICIPANT_IMAGE=go1-participant:example python3 -B tests/local_launch/smoke.py /tmp/go1-guide-pair-t5-20261115
SIM_IMAGE=registry.cookcloud.ru/go1-hackathon-remote-stage/go1-sim:v1.0 python3 -B tests/local_launch/lifecycle.py /tmp/go1-guide-lifecycle-20261115
git diff --check
```

Каталоги тестов должны быть новыми; выше записаны фактически использованные имена.
Readiness и short lifecycle проверки sim-only, ручной PTY shell проверялись
временными тестовыми harness `/tmp/go1-guide-check.py`,
`/tmp/go1-sim-lifecycle-check.py`, `/tmp/go1-manual-check.py`,
`/tmp/go1-manual-exit-check.py`. Они не входят в систему запуска и не нужны участникам.
Логи этих проверок: `/tmp/go1-guide-20261115/` и
`/tmp/go1-guide-manual-exit-20261115/`. Это локальные evidence, не Git artifacts.

## Simulator без Participant

Для T2/T3/T4/T5 1.0/T5 2.0 реально выполнялась следующая форма команды
с подстановкой task/width:

```bash
python3 run_local.py --task T2 --sim-only --sim-image registry.cookcloud.ru/go1-hackathon-remote-stage/go1-sim:v1.0 --participant-image missing:must-not-be-inspected --course-width 1.0 --logs
```

Все пять комбинаций PASS: readiness по payload, список nodes/topics, ровно один
контейнер по Compose project label; отсутствующий Participant image не проверялся
и Participant не создавался. T4/T5: реальный gzserver содержит `--lockstep`.
T2/T3/T4: SIGINT → 130; T5 обе ширины: SIGTERM → 143. После каждого case контейнер
удалён. Дополнительно PASS: readiness timeout 0.001 с, SIGINT во время startup,
kill Simulator после readiness → exit 1 и cleanup. GUI не испытывался.

## Ручной shell

Создан реальный интерактивный PTY:

```bash
SIM_IMAGE=registry.cookcloud.ru/go1-hackathon-remote-stage/go1-sim:v1.0 ROS_DOMAIN_ID=151 GO1_DDS_LOCAL=1 GO1_SIM_CYCLONEDDS_URI=file:///home/ros/ros2_custom_config_setup/cyclonedds_local.xml docker compose -f docker-compose.yml -f docker-compose.headless.yml run --rm --no-deps --pull never --name go1-manual shell
```

В нём выполнены все три source, `ros2 pkg prefix go1_simulation`,
`scenario.launch.py --show-args` и пять launch-команд из инструкции. Все достигли
readiness по реальным сообщениям; nodes/topics получены, для Gazebo подтверждены
world paths `odom_validation.world`, `course_w10.world`, `course_w20.world` и
`--lockstep`. Сценарии останавливались Ctrl+C с возвратом в Bash.
T4: `ros2 control list_controllers` показал active `joint_states_controller` и
`joint_group_effort_controller`; получен header front RGB. В Course получен
header rearDown depth. Логи подтверждают загрузку gazebo_ros2_control и CHAMP.
SHA256 установленных `scenario.launch.py`, `mujoco.launch.py`,
`go1_simulation.launch.py` совпали с текущими исходниками.
Попытка прочитать `/proc/gzserver/maps` запрещена окружением, поэтому независимая
проверка загруженных shared objects по maps не заявляется. Подключение IMU
проверяется payload в двухконтейнерном smoke.

**Ограничение остановки:** при Ctrl+C Gazebo выводил XIO/Boost mutex assertion,
contact_sensor и course_goal_sender также могли завершаться с ошибкой при
прерывании. Чистый exit всех дочерних процессов не подтверждён. Возврат в shell
и удаление `go1-manual` после `exit` подтверждены `docker ps -a`.
Первый harness ошибочно требовал exit 0 от shell после прерванного launch и
завершился assertion уже после всех пяти запусков и удаления контейнера.
Отдельный повтор T2: shell exit 0, удаление PASS.

## Совместный режим и lifecycle

Проверяется existing interface image `go1-participant:example`; пользователю
он не навязывается. Это транспортный smoke, без алгоритмов/движения/campaigns.
Каждая payload-проба занимает 20 с; Simulator readiness ограничен 90 с.

Первый общий smoke: T2 и T3 PASS; T4 readiness timeout с cleanup.
Он пересёкся с ручным Gazebo и другими проверками. Причина timeout отдельно
не доказана; одновременные Gazebo при host network не изолированы отдельными
Gazebo master ports. Повтор T4 выполнялся последовательно и прошёл.
Все дальнейшие Gazebo cases запускаются последовательно.

| Case | Получено внутри Participant | Получено внутри Simulator | Завершение |
|---|---|---|---|
| T2 | LowState 8029 | LowCmd 199 | SIGINT, 130, cleanup PASS |
| T3 | LowState 8330 | LowCmd 199 | kill Participant, 1, cleanup PASS |
| T4 (повтор) | scan 138, IMU 1365, front RGB 104/depth 103 | cmd_vel 401 | kill Simulator, 1, cleanup PASS |
| T5 2 м (повтор) | scan 32, IMU 319, front RGB/depth 24/24, каждая дополнительная RGB/depth 16/16 | cmd_vel 400 | SIGINT, 130, cleanup PASS |
| T5 1 м | scan 32, IMU 319, front RGB/depth 24/24, каждая из четырёх дополнительных RGB/depth 16/16 | cmd_vel 401 | SIGTERM, 143, cleanup PASS |

Существующий `lifecycle.py`: PASS invalid CLI, missing image, bad Participant,
readiness timeout, startup SIGINT, log followers, domain lock, явный
недоступный GPU request с понятной ошибкой и cleanup. `runtime_check.py`: PASS
create/start/ping и явный bind mount. CPU запуск не требует GPU.
`check_public_tree.py`, py_compile, Compose base/headless config, `git diff --check`
— PASS. Все 34 Bash-блока инструкции дополнительно проверены через `bash -n`.

GUI, аппаратный GPU, LAN, полные алгоритмы T2–T5, долговременная стабильность
и независимая новая source-сборка не проверялись. Варианты `ros2 topic echo`
проверены по CLI help; практически выполнены front RGB и rearDown depth echo,
остальные payload подтверждены Python probe, а не каждым отдельным CLI echo.
После подготовки инструкции существующие frozen/baseline images и артефакты
не перезаписывались.


T5 2 м, первая попытка: readiness и два контейнера PASS, однако 20-секундный
camera probe FAIL: front RGB/depth 0/0, остальные четыре RGB/depth по 18/18,
scan 35, IMU 337. Тест завершил launcher через SIGTERM, exit 143, контейнеры удалены.
Наличие сцены не выдано за подтверждение всех payload. Выполнен отдельный повтор:

```bash
SMOKE_CASE=T5-2 SIM_IMAGE=registry.cookcloud.ru/go1-hackathon-remote-stage/go1-sim:v1.0 PARTICIPANT_IMAGE=go1-participant:example python3 -B tests/local_launch/smoke.py /tmp/go1-guide-pair-t5w2-repeat-20261115
```

Повтор T5 2 м — PASS: front RGB/depth 24/24; четыре дополнительные RGB/depth
по 16/16; scan 32, IMU 319, обратный cmd_vel 400. SIGINT → 130, cleanup PASS.
Первый пропуск front payload остаётся наблюдаемой нестабильностью короткого
окна; причина не установлена. Гарантия доставки каждого кадра не заявляется.
Итоговая проверка `docker ps -a` не обнаружила контейнеров `go1-local-*`
или `go1-manual`. В Git включены только пять файлов этой задачи.
