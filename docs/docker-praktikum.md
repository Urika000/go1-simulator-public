# Практикум по Docker: компактная версия

| Где ты    | Приглашение терминала                            | Что здесь выполняется                                         |
|-----------|--------------------------------------------------|---------------------------------------------------------------|
| Хост      | `имя@компьютер:~$`                               | почти все команды `docker ...`, `git`, `xhost`, `cd`, `mkdir` |
| Контейнер | `root@3f2a1b4c5d6e:/#` (после `@` ID контейнера) | `apt`, `xclock`, `go1-sim`, `ros2 ...`                        |

Выйти из контейнера на хост: `exit` или `Ctrl+D`.

Текст в угловых скобках, например `<Ваша фамилия>`, это заглушка: подставь своё значение, а скобки убери.

## Часть 0. Подготовка окружения

Все команды выполняются на хосте, кроме шага 3 в пункте 0.3.

### 0.1. Установка Docker Engine и Compose (Ubuntu/Debian)

В стандартных репозиториях Ubuntu лежит устаревший `docker.io`, поэтому подключаем официальный репозиторий Docker.

```bash
# 1. Удаляем старые версии (если их не было, apt напишет "is not installed")
sudo apt remove docker docker-engine docker.io containerd runc

# 2. Зависимости
sudo apt update
sudo apt install -y ca-certificates curl gnupg

# 3. GPG-ключ
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 4. Репозиторий (архитектура и имя релиза подставляются автоматически)
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 5. Установка
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
```

Если у тебя Debian, в шагах 3 и 4 замени `ubuntu` на `debian`.

Что ставится: `docker-ce` (демон, фоновая служба), `docker-ce-cli` (команда `docker`), `containerd.io` (запускает контейнеры), `docker-buildx-plugin` (сборка образов), `docker-compose-plugin` (команда `docker compose`).

**Проверка**

```bash
sudo systemctl status docker     # ожидаем: Active: active (running); выход из окна: q
docker compose version           # ожидаем: Docker Compose version v2.x.x
```

Если служба не запущена: `sudo systemctl start docker`.

### 0.2. Доступ без sudo

Доступ к демону есть у root и у группы `docker`, поэтому добавляем себя в неё.

```bash
sudo usermod -aG docker $USER
newgrp docker      # применить группу в этом терминале (или перелогиниться)
docker run hello-world
```

**Ожидаемый вывод:** строка `Unable to find image ... locally`, затем `Hello from Docker!`.

Если видишь `permission denied while trying to connect to the Docker daemon socket`, группа не применилась: выполни `newgrp docker` ещё раз или выйди из учётной записи на хосте и зайди в неё снова.

Членство в группе `docker` фактически даёт права root. Для общих серверов используют Rootless mode, на личном компьютере это нормально.

### 0.3. Проброс X Server (для GUI-приложений)

У контейнера нет своего экрана. Чтобы окно программы из контейнера появилось у тебя, нужны три вещи: `xhost +local:docker` (разрешает Docker подключаться к экрану), `-e DISPLAY=$DISPLAY` (говорит, на какой экран рисовать) и `-v /tmp/.X11-unix:/tmp/.X11-unix` (пробрасывает сокет X Server). Это понадобится для симулятора в Части 2.

**Шаги 1 и 2. На хосте**

```bash
xhost +local:docker
docker run -it --rm \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  ubuntu:latest bash
```

Флаги: `-it` даёт интерактивный терминал внутри контейнера, `--rm` удалит контейнер после выхода. Приглашение сменится на `root@<ID>:/#`: ты внутри контейнера.

**Шаг 3. В контейнере**

```bash
apt update && apt install -y x11-apps && xclock
```

**Ожидаемый результат:** на рабочем столе открывается окно с часами (терминал при этом занят ими).

**Шаг 4. Выход**

Закрой окно часов, введи `exit`. Контейнер удалится сам, ты снова на хосте. После работы можно закрыть доступ обратно командой `xhost -local:docker`. Пока открыт доступ, любой локальный контейнер может видеть твой экран.

### 0.4. Проверка готовности

```bash
docker --version
docker compose version
SURNAME=<Ваша фамилия>                   # нужен только для МК
echo $SURNAME
```

`docker --version` должен вывести версию, `docker compose version` версию `v2.x.x`, `echo $SURNAME` твою фамилию.

`SURNAME` это переменная окружения. Правила: скобки `< >` убери (`SURNAME=ivanova`), пиши латиницей, без пробелов и **без пробелов вокруг** `=`. Фамилия в теге нужна, чтобы твои образы в общем registry не затирали образы других участников.

Переменная живёт только в том терминале, где её задали. Чтобы не задавать заново, на время практикума добавь в конец файла `~/.bashrc` строку `export SURNAME=ivanova` и открой новый терминал.

## Часть 1. Основной практикум

Цель: полный цикл «скачать, пометить, запустить, залить на сервер, запустить через Compose, собрать свой образ, залить». Все команды на хосте.

Понятия:

| Понятие       | Что это                                                                                                                                                                            |
|---------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Образ (image) | готовый шаблон: файлы и программы, упакованные вместе, только для чтения                                                                                                           |
| Контейнер     | запущенный экземпляр образа                                                                                                                                                        |
| Тег (tag)     | метка на образе, например `latest` или `ivanova`. Теги нужны в том числе для того, чтобы потом отправить образ на сервер (`push`): для этого его помечают именем с адресом сервера |
| Registry      | сервер для хранения образов: сюда `push`, отсюда `pull`                                                                                                                            |
| Compose       | описание запуска в файле `compose.yaml` вместо длинной команды                                                                                                                     |

### Шаг 1. Pull и смена тега

```bash
docker pull hello-world
docker tag hello-world some_new_tag/hello-world:$SURNAME
docker images | grep hello-world
```

`pull` скачивает образ из Docker Hub (без тега берётся `latest`). `tag` вешает на него второе имя. Формат имени: `[сервер/][репозиторий/]имя:тег`.

**Ожидаемый вывод:** две строки, `hello-world latest` и `some_new_tag/hello-world ivanova`, с **одинаковым** `IMAGE ID`. Если тег пустой, не задана `SURNAME`.

### Шаг 2. Запуск через docker run

**Одноразовый запуск**

```bash
docker run --rm hello-world
docker ps
```

`docker ps` показывает запущенные сейчас контейнеры. **Ожидаемо:** `Hello from Docker!` и пустая таблица, потому что процесс напечатал фразу и завершился, а `--rm` удалил контейнер. Без `--rm` он остался бы в состоянии `Exited`.

**Контейнер, который продолжает работать**

Контейнер живёт, пока работает его главный процесс. У `bash` процесс сам не завершается: он принимает команды одну за другой, пока ты не введёшь `exit`, поэтому контейнер остаётся.

```bash
# терминал 1
docker run --rm -it ubuntu bash

# терминал 2 (на хосте)
docker ps
```

**Ожидаемо:** в `docker ps` одна строка с `IMAGE ubuntu`, `COMMAND "bash"`, `STATUS Up ...` и случайным именем в `NAMES`. После `exit` в терминале 1 контейнер исчезает.

### Шаг 3. Push в свой registry

```bash
docker tag hello-world registry.cookcloud.ru/master-class-repo/hello-world:$SURNAME
docker login registry.cookcloud.ru
docker push registry.cookcloud.ru/master-class-repo/hello-world:$SURNAME
# Login: student
# Password: 3nU-f65-84J-7gT
```

Имя образа содержит адрес сервера (`registry.cookcloud.ru`), раздел (`master-class-repo`), имя и тег: по нему Docker понимает, куда отправлять.

Без `login` `push` завершится ошибкой вроде `no basic auth credentials`: сервер не знает, кто ты.

**Ожидаемо:** `Login Succeeded` (может быть предупреждение про хранение данных без шифрования, для учебного аккаунта это допустимо), затем при `push` строки `Pushed` по слоям и итоговая `ivanova: digest: sha256:... size: ...`.

Вместо `Pushed` у слоёв может быть `Layer already exists`: такой слой уже есть на сервере. В конце может появиться строка `Info → Not all multiplatform-content is present and only the available single-platform image was pushed`. Это не ошибка: образ `hello-world` содержит варианты под разные архитектуры процессора, а залился только тот, который скачан на твой компьютер. Для практикума это не важно.

### Шаг 4. Запуск через Compose

Compose запускает сервисы по описанию в файле: вместо длинной команды `docker run` с флагами достаточно `docker compose up`. Compose понадобится и в Части 2.

```bash
mkdir mc_project
cd mc_project
echo 'SURNAME='$SURNAME > .env
```

`.env` Compose читает автоматически и подставляет значения в `compose.yaml`. Проверка: `cat .env` выводит `SURNAME=ivanova`.

Создай рядом файл `compose.yaml`:

```yaml
services:
  hello:
    image: registry.cookcloud.ru/master-class-repo/hello-world:$SURNAME
```

`services` это список сервисов, `hello` имя сервиса (любое), `image` образ. Отступы только пробелами.

Запускаем сервис, смотрим его вывод и убираем:

```bash
docker compose up -d
docker compose logs
docker compose down
```

| Команда                | Что делает                                       | Ожидаемый вывод                                              |
|------------------------|--------------------------------------------------|--------------------------------------------------------------|
| `docker compose up -d` | создаёт и запускает сервис в фоне                | `Container mc_project-hello-1 Started`. `-d` значит «в фоне» |
| `docker compose logs`  | показывает всё, что сервис напечатал             | `hello-1  \\| Hello from Docker!`                            |
| `docker compose down`  | останавливает и удаляет контейнер и сеть проекта | строки `Container ... Removed`, `Network ... Removed`        |

Особенность Compose: если нужного образа нет на компьютере, он скачает его сам с указанного в названии образа сервера. Чтобы это увидеть, перед `docker compose up -d` удали локальные имена образа: `docker rmi hello-world some_new_tag/hello-world:$SURNAME registry.cookcloud.ru/master-class-repo/hello-world:$SURNAME`. В выводе `up` тогда появятся строки `Pulling` и `Pulled`.

### Шаг 5. Свой Dockerfile и сборка

Схема: **Dockerfile** (инструкция) → `docker build` → **образ** → `docker run` → **контейнер**.

Создай файл `Dockerfile` (без расширения, с большой буквы) в любой пустой папке и запиши в него:

```dockerfile
FROM alpine:3.20
CMD ["echo", "Привет от моего первого образа!"]
```

`FROM` задаёт базовый образ (крошечный Linux Alpine), `CMD` команду, которая выполняется при запуске контейнера.

```bash
docker build -t my-hello:$SURNAME .
docker run --rm my-hello:$SURNAME
```

Точка в конце означает «Dockerfile лежит в текущей папке», не забудь её. **Ожидаемо:** сборка заканчивается строкой вида `naming to docker.io/library/my-hello:ivanova`, а запуск печатает `Привет от моего первого образа!` и сразу завершается.

### Шаг 6. Push своего образа

```bash
docker tag my-hello:$SURNAME registry.cookcloud.ru/master-class-repo/my-hello:$SURNAME
docker push registry.cookcloud.ru/master-class-repo/my-hello:$SURNAME
```

**Ожидаемо:** как в Шаге 3, `Pushed` по слоям и итоговая строка `digest: sha256:...`. Заново входить на сервер не нужно.

## 