#!/usr/bin/env bash
# выходим при любой ошибке
set -euo pipefail
# задаем путь из которого запущен скрипт
SCRIPT_DIR="$(cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)"
# подключаем переменные окружения
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env}"

# проверяем и загружаем переменные окружения .env
if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
else
  echo "Файл переменных окружения .env не найден: ${ENV_FILE}. Скопируйте файл и запустите заново."; exit 1
fi
# проверяем наличие обязательных переменных окружения
REQUIRED_VARS=(
  SECRET_KEY
  DEBUG
  ALLOWED_HOSTS
  POSTGRES_USER
  POSTGRES_PASSWORD
  POSTGRES_DB
  POSTGRES_HOST
  POSTGRES_PORT
  YOOKASSA_SHOP_ID
  YOOKASSA_SECRET_KEY
)
missing=()
for v in "${REQUIRED_VARS[@]}"; do
  # shellcheck disable=SC2154
  if [[ -z "${!v:-}" ]]; then
    missing+=("$v")
  fi
done

if (( ${#missing[@]} > 0 )); then
  echo "Отсутствуют обязательные переменные в ${ENV_FILE}: ${missing[*]}"
  exit 1
fi

echo "Установка Docker"

# отключаем интерактивные вопросы
export DEBIAN_FRONTEND=noninteractive
# включаем проверку после установки docker
SKIP_HELLO="${SKIP_HELLO:-false}"

# проверка прав пользователя
if [[ $EUID -ne 0 ]]; then
  echo "У вашего пользователя недостаточно прав - запустите с правами root"; exit 1
fi
# проверка возможности установки
source /etc/os-release || { echo "Невозможно прочитать вашу ОС"; exit 1; }
case "${ID}:${VERSION_CODENAME:-}" in
  ubuntu:jammy|ubuntu:noble|debian:bookworm)
    : ;;
  ubuntu:*)
    echo "Неподдерживаемая Ubuntu: ${VERSION_CODENAME:-unknown} (поддерживаемые 22.04/24.04)"; exit 1 ;;
  debian:*)
    echo "Неподдерживаемая Debian: ${VERSION_CODENAME:-unknown} (поддерживаемые 12)"; exit 1 ;;
  *)
    echo "Неподдерживаемая ОС: ${ID}. Только Ubuntu 22.04/24.04 или Debian 12."; exit 1 ;;
esac

# обновляем пакеты
apt-get -qq update
# устанавливаем ключи
apt-get install -y -qq --no-install-recommends ca-certificates curl gnupg lsb-release
# удаляем старые пакеты
apt-get remove -y -qq docker docker-engine docker.io docker-doc docker-compose \
  podman-docker containerd runc || true

# создаем каталог для ключей
install -m 0755 -d /etc/apt/keyrings
# скачиваем ключ при отсутствии
if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
  curl -fsSL "https://download.docker.com/linux/${ID}/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
fi
# архитектура
ARCH="$(dpkg --print-architecture)"
# дистрибутив
CODENAME="${VERSION_CODENAME:-$(lsb_release -cs)}"
# подключаем docker
echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${ID} ${CODENAME} stable" \
  | tee /etc/apt/sources.list.d/docker.list >/dev/null
# обновляем пакеты
apt-get update -y

# установка docker engine, compose
apt-get install -y -qq --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# запуск и автозапуск
systemctl enable --now docker

# тестовый контейнер
if [[ "${SKIP_HELLO}" != "true" ]]; then
  docker run --rm hello-world || true
fi

echo "Установка Docker завершена!"

echo "Клонирование репозитория"
# устанавливаем git
apt-get install -y -qq --no-install-recommends git

# задаем переменные
REPO_URL="${REPO_URL:-https://github.com/Itsmyusername/dvmn_meetuptg_bot.git}"
BRANCH="${BRANCH:-main}"
PARENT_DIR="${PARENT_DIR:-/opt}"
REPO_NAME="$(basename -s .git "${REPO_URL}")"
REPO_DIR="${REPO_DIR:-${PARENT_DIR}/${REPO_NAME}}"
cd "${PARENT_DIR}"
# устанавливаем или обновляем
if [[ -d "${REPO_DIR}/.git" ]]; then
  cd "${REPO_DIR}"
  git fetch --all --prune
  git checkout "${BRANCH}"
  git pull --ff-only origin "${BRANCH}"
else
  git clone --branch "${BRANCH}" --single-branch "${REPO_URL}" "${REPO_DIR}"
  cd "${REPO_DIR}"
fi

echo "Репозиторий склонирован!"

# копируем .env
cp -f "${ENV_FILE}" "${REPO_DIR}/.env"
echo "Переменные окружения скопированы!"

# монтирование и запуск контейнеров
cd "${REPO_DIR}/production_deployment"
docker compose -f docker-compose-prod.yml pull || true
docker compose -f docker-compose-prod.yml up -d --remove-orphans

echo "Деплой завершен успешно!"