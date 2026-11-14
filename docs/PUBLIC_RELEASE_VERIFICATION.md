# Проверка публичной поставки — 14.11.2026

## Происхождение и состав

Источник: commit `76c2bd4915655e72a459281042cf87646e089af4`.
HEAD совпал с ожидаемым, исходный Git status был чистым. Исходное дерево,
официальный Judge, образы frozen candidates и baselines не изменялись.
Публичный каталог создан отдельно, `git init -b main`; это не worktree,
`.git` и история источника не копировались. Push/публикация не выполнялись.

Положительный список: Dockerfile/Compose/build script, LOCAL Python launcher и
runtime, четыре пакета Go1, публичные модели/карты/миры, IMU vendor source,
DDS/config, standalone dependency preparation и lockfile, минимальные
transport/lifecycle tests, новый Participant interface example, README и licenses.
В `go1_ws` 91 сохранённый файл побайтно совпадает с источником; изменены только
MuJoCo GT adapter, Gazebo xacro и CMake регистрации удалённого private GT plugin.
Контроллеры, meshes, параметры физики, сенсоров и public ROS topic mappings
не менялись. `odom_validation.world` — необходимый публичный T4-сценарий,
а не скрытая трасса. Course 1/2 м включены вместе с картами и ArUco textures.

Исключены целиком Judge/scoring/runtime/security/firewall и их Dockerfiles,
конфигурации official launch/bridge, закрытые fixtures/результаты, внутренние
reports/docs/scripts, исторические архивы. Не переносился весь каталог tests.
Удалены также встроенные в Simulator private GT socket serializers и
Gazebo private GT plugin/подключение. Публичная диагностическая одометрия сохранена.
Полный Participant/ONNX и training snapshots исключены из-за ненужной для
Simulator цепочки происхождения; новый interface example явно не решает задания.

## Окружение и команды

Ubuntu 22.04.5 amd64, Python 3.10.12, Docker 29.9.3, Compose 5.7.0.
Все команды выполнялись из корня публичного репозитория:

```bash
CACHE_OFFLINE=1 bash scripts/prepare-standalone-cache.sh
bash scripts/prepare-standalone-cache.sh
SIM_IMAGE=go1-sim:public BUILD_JOBS=1 bash build_image.sh
docker compose config --quiet
docker compose -f docker-compose.yml -f docker-compose.headless.yml config --quiet
python3 -B run_local.py --help
PARTICIPANT_IMAGE=go1-participant:local-python python3 -B tests/local_launch/runtime_check.py
SIM_IMAGE=go1-sim:clean-69dadf3 PARTICIPANT_IMAGE=go1-participant:local-python \
  INTERFACE_ONLY=0 python3 -B tests/local_launch/smoke.py /tmp/go1-public-existing-smoke
```

Dependency bundle импортирован в игнорируемый локальный `.dependency-cache`;
проверены четыре Git revisions, libchamp revision, source manifests и wheel hashes.
Online preparer самостоятельно собрал download helpers из CookCloud и проверил
существующий source cache. Он не использует Judge Dockerfiles.

База именно `registry.cookcloud.ru/base_images/ros2-base-humble-amd64:v1.0.1`,
локальный ID `4d4a184901f154849d59477a077ce507f31fdf63b8bedd8caea460607eec243d`.
`docker manifest inspect` прошёл; независимый запрос без Docker credentials
прошёл bearer challenge и получил manifest HTTP 200. Это проверка текущего
анонимного доступа к manifest, не обещание будущих прав или скачивания всех слоёв.
Участникам требуется доступ к CookCloud registry; базу не заменяли.

## Сборка публичных образов — PASS

Из этого дерева реально собран `go1-sim:public`:
`sha256:c79ddbece6cc7d00f114a9a9a09be0bae061ebb35ca722bcbe51bf75fce1b2e3`.
FROM — согласованная CookCloud-база, не прежний Simulator image.
Системные слои взяты из Docker cache; девять ROS-пакетов компилировались заново.
Source-built IMU plugin также собран штатным скриптом. Встроенные проверки
Unitree messages, xacro/check_urdf/YAML, meshes, Course maps/textures, soft stand,
launch loading, MuJoCo model и hash-locked wheels прошли. Последующий cached
build добавил финальные MIT notices. Это source build, не запуск старого image.

`go1-participant:example` также собран из публичного контекста:
`sha256:b60a77b08185ff235b5a8dafba95c4154737dcaf790380a17c649e8e5cb7bbf2`.
Реальный headless Compose Shell подтвердил ROS package, MuJoCo 3.3.7,
20 motor slots, наличие публичного T4 world и MIT notices, отсутствие private GT
library/serializers в установленном Simulator workspace.

```bash
DOCKER_BUILDKIT=0 docker build --build-arg SIM_IMAGE=go1-sim:public \
  -t go1-participant:example participant_example
python3 -B tests/local_launch/runtime_check.py
python3 -B tests/local_launch/smoke.py /tmp/go1-public-source-smoke
python3 -B tests/local_launch/lifecycle.py /tmp/go1-public-lifecycle
strace -f -e trace=%file -o /tmp/go1-public-portable.strace \
  python3 -B tests/local_launch/portable.py
```

## Готовый внешний Participant image

Явный `--participant-image go1-participant:local-python` использован без
исходников Participant на хосте. T2/T3/T4/T5 width 1.0: PASS — двусторонние
DDS payloads и cleanup. Проверялись `/lowstate`/`/lowcmd`, `/scan`, `/imu/data`,
front RGB (T4), пять RGB (T5), обратные `/odom` и `/cmd_vel`.
Первая T5 width 2.0 при параллельной компиляции не получила front RGB за 12 с:
FAIL этой конкретной попытки, остальные четыре RGB и транспорт работали.
Причинная связь с нагрузкой не доказана. Повтор без компиляции, окно 20 с:
PASS, все пять RGB (6–11 сообщений) и depth (6–9 сообщений), `/odom` 23,
`/cmd_vel` 371. Контейнеры очищены после обеих попыток.

```bash
SIM_IMAGE=go1-sim:clean-69dadf3 PARTICIPANT_IMAGE=go1-participant:local-python \
  INTERFACE_ONLY=0 SMOKE_CASE=T5-2.0 python3 -B tests/local_launch/smoke.py \
  /tmp/go1-public-existing-course2-retry
```

## Диагностика camera QoS

Первая source-image серия: T2/T3/T4 PASS, T5 width 1.0 FAIL в 20-секундном
окне — front RGB/depth 0, остальные четыре RGB-D работали; cleanup PASS.
Отдельная диагностика в том же неизменённом Simulator подтвердила publisher
`camera_driver` с QoS RELIABLE. Хост: `net.core.rmem_max=212992`,
`net.core.wmem_max=212992`. Ранний BEST_EFFORT front probe получил лишь 1/1
RGB/depth за 30 с, последующий RELIABLE probe — 27/27 front и по 17/17
для остальных четырёх камер за 20 с. Это согласуется с потерями больших raw
UDP samples, но не доказывает единственную причину каждой потери.

Исправлен только test probe: Image subscriptions используют предлагаемый
publisher QoS RELIABLE с retransmission; scan/IMU/LowState остаются sensor-data.
Это изменение измерения, не workaround в Simulator. XML DDS, Linux sysctl,
частоты/размеры камер, physics и launch arguments не менялись. README объясняет
этот выбор QoS. Повторные source-image T5 используют 20-секундное окно.

```bash
SMOKE_CASE=T5 python3 -B tests/local_launch/smoke.py /tmp/go1-public-source-t5-reliable
```

## Итоговые source-image transport/lifecycle проверки — PASS

| Task / width | Входные sensor payloads | Обратный DDS | Exit / cleanup |
|---|---|---|---|
| T2 / 1.0 | lowstate 8058 | /lowcmd 199 | 130 / PASS |
| T3 / 1.0 | lowstate 8016 | /lowcmd 200 | 1 / PASS |
| T4 / 1.0 | scan 109, IMU 1085; RGB/depth min 9 | /cmd_vel 400 | 1 / PASS |
| T5 / 1.0 | scan 35, IMU 345; RGB/depth min 17 | /cmd_vel 401 | 143 / PASS |
| T5 / 2.0 | scan 28, IMU 282; RGB/depth min 15 | /cmd_vel 400 | 130 / PASS |

Это совокупность успешных T2/T3/T4 первой серии и двух повторных T5 с
RELIABLE Image reader; первая серия целиком не была green из-за описанной выше
ошибки измерения. На каждом case ровно два целевых контейнера, одинаковый DDS
domain, headless, Gazebo фактически с `--lockstep`. Inspect обоих контейнеров:
CPU quota/NanoCpus/Memory=0, PidsLimit=null/0, User совпадает с образом;
нет неявных bind mounts. Participant также без дополнительных capabilities,
security options, read-only rootfs и GPU request по умолчанию.
В T2/T3 interface example не является controller: нулевой LowCmd отправляет
тестовый probe. T4/T5 example и probe отправляют нулевой Twist. Полноценное
решение задач этими counts не подтверждается.

Runtime create → created → start → ping → exit0 → stop/remove: PASS;
readonly bind с пробелами и `$()` передан одним argv без shell expansion.
Lifecycle: invalid CLI, missing image, bad participant, readiness timeout,
startup Ctrl+C всей process group, logs + Ctrl+C, domain reservation и
недоступный explicit GPU request — PASS с cleanup. CPU-only launch не требует GPU.

Portable T4: временный bundle содержит только launcher/runtime, Compose и DDS;
исходников Participant нет. Явный image, readonly marker bind, 41 `/cmd_vel`,
SIGTERM143 и cleanup: PASS. `strace -f -e trace=%file` всей этой проверки не
содержит обращений к внутреннему исходному репозиторию или соседним worktrees;
проверены также mounts. Это фактическая проверка независимости, не только grep.
На завершении LOCAL-контейнеров не осталось.

Compose base/headless, help, Bash syntax, Python AST и 24 XML resources: PASS.
Положительный список и новая история проверяются `python3 -B tests/check_public_tree.py`:
один самостоятельный root commit; нет Judge paths, private GT implementation,
внутренних абсолютных путей, известных token/private-key signatures. Дополнительный
ручной поиск не выявил секретов; ownership UUID `token` в runtime — локальная
метка владения контейнером. Docker COPY inputs доступны. Git clean, remote не задан.
Исходный HEAD/status повторно подтверждены без изменений.

Evidence вне Git: `/tmp/go1-public-*.log`, `/tmp/go1-public-source-smoke/`,
`/tmp/go1-public-source-t5-reliable/`, `/tmp/go1-public-lifecycle/`,
`/tmp/go1-public-portable.strace`. Это временные локальные логи; существенные
результаты сохранены здесь. Frozen artifacts не продвигались в release.

## Границы

Новая сборка использует Docker layer cache для системных зависимостей;
это не `--no-cache` и не доказательство установки на полностью чистой машине.
Загрузка всех sources с пустым cache, GUI/GPU/LAN и длительные T4/T5/Nav2 campaigns
**NOT VERIFIED**. Apt не закреплён snapshot-датой; bit-identical builds не обещаются.
Smoke проверяет DDS transport и lifecycle, а не качество алгоритмов/scoring.

Владелец проекта 14.11.2026 выбрал MIT для всего оригинального кода.
Добавлены корневой LICENSE и копия в licenses/ для включения в Docker image.
Сторонние лицензии/notices сохранены; MIT не перелицензирует upstream.
Перед публикацией нужно подтвердить участникам поддерживаемый порядок доступа
к CookCloud. Публикация ожидает review владельца.
