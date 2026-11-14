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
