# Лицензии и происхождение

- `Unitree-Go1-LICENSE`: BSD-3-Clause Unitree Robotics для модели Go1;
  `go1_description/package.xml` также объявляет BSD-3-Clause.
- `CHAMP-LICENSE`: лицензия upstream CHAMP; уведомления в производных
  конфигурациях/исходниках сохранены.
- Source-built IMU: `vendor/gazebo_ros_imu/LICENSE` (Apache-2.0), заголовки
  upstream сохранены; README описывает исправление timestamp.
- Подготовка зависимостей сохраняет upstream LICENSE в каждом source bundle:
  Unitree ROS 2, CHAMP/libchamp, MuJoCo Menagerie/Unitree Go1, OSRF gazebo_models.
  Их revisions закреплены в Dockerfile, source bundles и wheels не входят в Git.
  У отдельных моделей Gazebo могут быть собственные notices в model.config.
- Python wheels и системные ROS/Ubuntu пакеты сохраняют лицензии в образе.

Оригинальный код Hackathon Go1, включая launcher, runtime, собственные ROS
узлы/добавления и interface example, распространяется под MIT по решению
владельца проекта от 14.11.2026: корневой `LICENSE` и `Project-MIT-LICENSE`.
MIT не заменяет лицензии сторонних частей. Исходные BSD-3-Clause declarations
в ROS package.xml сохранены для заимствованных компонентов; оригинальные
добавления проекта лицензированы MIT. Заголовки и notices upstream сохранены.

Полный Participant с обученными ONNX policies не включён: для публичного
Simulator достаточно отдельного примера интерфейса, без переноса цепочки
происхождения training snapshots и моделей. `participant_example` — новый
минимальный пример, а не эталонное решение T2–T5.
