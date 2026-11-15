# Состояние публичного Simulator

Публичная копия имеет самостоятельную Git-историю и не использует исходники
внутреннего проекта при сборке или запуске. Официальный Judge и frozen artifacts
не входят в поставку. Первичный source commit записан только для прослеживаемости
в PUBLIC_RELEASE_VERIFICATION.md.

Состав: MuJoCo/Gazebo/Course/Shell, ROS packages и модели, source-built IMU,
Python LOCAL launcher/runtime, DDS, dependency preparer/lockfile, минимальный
Participant interface example и короткие transport/lifecycle tests.

Результаты фактических проверок и ограничения:
[PUBLIC_RELEASE_VERIFICATION.md](PUBLIC_RELEASE_VERIFICATION.md).
Обновляйте этот файл и отчёт при изменении подтверждённого состояния.

14.11.2026 — VERIFIED: новая source-сборка из CookCloud, Participant interface
image build, T2/T3/T4/T5 (1/2 м), двусторонний DDS, все пять RGB-D, Shell,
runtime/ping/mounts, lifecycle/cleanup, отсутствие LOCAL resource/user overrides,
portable bundle + strace без внутреннего source access. Camera smoke использует
предлагаемый RELIABLE QoS; ранние потери BEST_EFFORT описаны в отчёте.
MIT для всего оригинального кода утверждена владельцем; notices upstream сохранены.
NOT VERIFIED: загрузка с полностью пустым cache, GUI/GPU/LAN, full Nav2/campaigns.
Ожидается review перед публикацией; push не выполнялся.


15.11.2026 — инструкция запуска: добавлены
[SIMULATOR_LAUNCH_GUIDE_RU.md](SIMULATOR_LAUNCH_GUIDE_RU.md) (включая подготовку
Ubuntu/GitHub/Harbor) и минимальный `run_local.py --sim-only` через тот же Compose.
Harbor v1.0 digest c79ddbece6cc7d00f114a9a9a09be0bae061ebb35ca722bcbe51bf75fce1b2e3
повторно подтверждён pull/inspect. VERIFIED: sim-only и ручной shell T2/T3/T4/T5
1/2 м, readiness и cleanup; совместные T2/T3/T4 и T5 1/2 м, DDS/camera payload,
existing lifecycle/runtime checks. T5 2 м: первое окно без front frames, повтор
получил все пять RGB/depth; стабильность каждого короткого окна не подтверждена.
Ручная остановка Gazebo выводит XIO/Boost mutex assertion, хотя возврат в shell
и удаление контейнера подтверждены. Один T4 readiness timeout при пересечении
проверок; последовательный повтор PASS. Результаты, counts и ограничения:
[SIMULATOR_LAUNCH_VERIFICATION_RU.md](SIMULATOR_LAUNCH_VERIFICATION_RU.md).
GUI/GPU/LAN/full campaigns остаются NOT VERIFIED. Push не выполнялся.
