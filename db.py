import configparser
import logging
import re
from contextlib import contextmanager
from pathlib import Path

import psycopg2
from psycopg2 import errors, sql

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_FILE = BASE_DIR / "schema.sql"
CONFIG_FILE = BASE_DIR / "config.ini"
LOG_FILE = BASE_DIR / "app.log"
SCHEMA = "ddos_ai"

# Логирование
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    encoding="utf-8",
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("ddos_lab")

CHECK_TEXT = {
    "chk_models_name": "название модели должно содержать не менее 3 символов",
    "chk_models_version": "версия должна быть в формате 1, 1.0 или 1.0.0",
    "chk_datasets_records": "число записей должно быть больше 0",
    "chk_datasets_attacks": "нужно выбрать хотя бы один тип атаки",
    "chk_datasets_date": "дата сбора не может быть раньше 2000-01-01",
    "chk_experiments_title": "название эксперимента должно содержать не менее 3 символов",
    "chk_runs_no": "номер запуска должен быть больше 0",
    "chk_runs_precision": "Precision должен быть в диапазоне 0..1",
    "chk_runs_recall": "Recall должен быть в диапазоне 0..1",
    "chk_runs_f1": "F1 должен быть в диапазоне 0..1",
    "chk_runs_latency": "задержка не может быть отрицательной",
    "chk_runs_epochs": "число эпох должно быть от 1 до 1000",
    "chk_runs_features": "нужно указать хотя бы один признак",
    "chk_runs_completed": "у завершённого запуска (completed) должен быть указан F1",
}

UNIQUE_TEXT = {
    "uq_models_name": "модель с таким названием уже есть",
    "uq_datasets_name": "датасет с таким названием уже есть",
    "uq_experiments_title_model": "у этой модели уже есть эксперимент с таким названием",
    "uq_runs_experiment_no": "в этом эксперименте уже есть запуск с таким номером",
}

COLUMN_TEXT = {
    "name": "Название", "family": "Семейство", "version": "Версия", "source": "Источник",
    "records": "Число записей", "collected_on": "Дата сбора", "title": "Название",
    "model_id": "Модель", "target_attack": "Целевая атака", "started_on": "Дата начала",
    "experiment_id": "Эксперимент", "run_no": "Номер запуска", "status": "Статус",
    "started_at": "Время запуска", "epochs": "Эпохи", "feature_set": "Признаки",
    "attack_types": "Типы атак",
}


class DbError(Exception):
    pass


# Текст ошибки
def safe_str(e):
    try:
        return str(e).strip()
    except Exception:
        return repr(e)


# Перевод ошибки в понятное сообщение
def human_error(e, op="insert"):
    d = getattr(e, "diag", None)
    constraint = getattr(d, "constraint_name", None)
    column = getattr(d, "column_name", None)
    if op == "ddl":
        if isinstance(e, errors.NotNullViolation):
            return f"Нельзя установить NOT NULL: в столбце «{column}» есть пустые (NULL) значения."
        if isinstance(e, errors.UniqueViolation):
            return "Нельзя добавить UNIQUE: в данных уже есть повторяющиеся значения."
        if isinstance(e, errors.CheckViolation):
            return "Нельзя добавить CHECK: существующие строки не удовлетворяют условию."
        if isinstance(e, errors.ForeignKeyViolation):
            return "Нельзя добавить FOREIGN KEY: есть значения, для которых нет записи в родительской таблице."
    if isinstance(e, errors.UniqueViolation):
        return f"Нарушение UNIQUE: {UNIQUE_TEXT.get(constraint, constraint)}."
    if isinstance(e, errors.NotNullViolation):
        return f"Нарушение NOT NULL: не заполнено обязательное поле «{COLUMN_TEXT.get(column, column)}»."
    if isinstance(e, errors.CheckViolation):
        return f"Нарушение CHECK: {CHECK_TEXT.get(constraint, f'не выполнено условие {constraint}')}."
    if isinstance(e, errors.DuplicateColumn):
        return "Столбец с таким именем уже есть в таблице."
    if isinstance(e, errors.DuplicateTable):
        return "Таблица или представление с таким именем уже существует."
    if isinstance(e, errors.DuplicateObject):
        return "Объект с таким именем уже существует (тип, значение ENUM или ограничение)."
    if isinstance(e, errors.InvalidParameterValue):
        return "Неверный параметр: например, такого значения ENUM нет."
    if isinstance(e, errors.CardinalityViolation):
        return "Скалярный подзапрос вернул больше одной строки — используйте агрегат, ANY/ALL или IN."
    if isinstance(e, errors.UndefinedColumn):
        return "Столбец не найден (возможно, он переименован или удалён)."
    if isinstance(e, errors.UndefinedObject):
        return "Не найден тип данных или ограничение с таким именем."
    if isinstance(e, errors.DependentObjectsStillExist):
        return "От объекта зависят другие (столбец таблицы, внешний ключ и т.п.). Отметьте CASCADE или сначала удалите зависимость."
    if isinstance(e, errors.InvalidForeignKey):
        return "Внешний ключ должен ссылаться на столбец с PRIMARY KEY или UNIQUE."
    if isinstance(e, (errors.DatatypeMismatch, errors.CannotCoerce)):
        return "Несоответствие типов: значения нельзя автоматически привести к нужному типу (попробуйте USING)."
    if isinstance(e, errors.GroupingError):
        return "Столбец должен входить в GROUP BY или использоваться внутри агрегатной функции."
    if isinstance(e, errors.UndefinedFunction):
        return "Операция или функция не применима к этим типам данных (например, AVG для текста или сравнение разных типов)."
    if isinstance(e, errors.InvalidRegularExpression):
        return "Неверное регулярное выражение."
    if isinstance(e, errors.SyntaxError):
        return "Синтаксическая ошибка в SQL-выражении. Проверьте введённое условие или значение."
    if isinstance(e, errors.InvalidTableDefinition):
        return ("Недопустимое изменение определения. Для представления OR REPLACE не может удалять, "
                "переименовывать или менять тип столбцов — удалите представление и создайте заново.")
    if isinstance(e, errors.ObjectNotInPrerequisiteState):
        return "Материализованное представление ещё не заполнено данными — нажмите «Обновить (REFRESH)»."
    if isinstance(e, errors.WrongObjectType):
        return "Операция не подходит для этого вида объекта (таблица, VIEW или MATERIALIZED VIEW)."
    if isinstance(e, errors.FeatureNotSupported):
        return "Эта операция не поддерживается для выбранного объекта."
    if isinstance(e, (errors.ForeignKeyViolation, errors.RestrictViolation)):
        if op == "delete":
            return f"Нарушение FOREIGN KEY ({constraint}): на запись ссылаются другие таблицы, удаление запрещено."
        return f"Нарушение FOREIGN KEY ({constraint}): указанная родительская запись не существует."
    if isinstance(e, errors.NumericValueOutOfRange):
        return "Несоответствие типов: число вне допустимого диапазона для столбца."
    if isinstance(e, (errors.InvalidDatetimeFormat, errors.DatetimeFieldOverflow)):
        return "Несоответствие типов: дата/время указаны неверно (ожидается ГГГГ-ММ-ДД или ГГГГ-ММ-ДД ЧЧ:ММ)."
    if isinstance(e, errors.InvalidTextRepresentation):
        return "Несоответствие типов: значение не подходит к типу столбца (число, дата или ENUM)."
    if isinstance(e, errors.StringDataRightTruncation):
        return "Несоответствие типов: строка длиннее допустимого размера столбца."
    if isinstance(e, errors.UndefinedTable):
        return "Таблица не найдена: возможно, она переименована. Иначе нажмите «Создать схему и таблицы»."
    if isinstance(e, psycopg2.DataError):
        return f"Несоответствие типов: {safe_str(e)}"
    if isinstance(e, (psycopg2.OperationalError, psycopg2.InterfaceError)):
        return "Потеряно соединение с PostgreSQL. Подключитесь заново."
    return f"Ошибка БД: {safe_str(e)}"


# Чтение настроек подключения
def load_config():
    cfg = {"host": "localhost", "port": "5432", "dbname": "ddos_lab", "user": "postgres", "password": ""}
    parser = configparser.ConfigParser()
    if parser.read(CONFIG_FILE, encoding="utf-8") and parser.has_section("postgresql"):
        cfg.update(parser["postgresql"])
    return cfg


class Database:
    def __init__(self):
        self.conn = None

    # Подключение
    def connect(self, host, port, dbname, user, password):
        self.close()
        log.info("Попытка подключения: %s@%s:%s/%s", user, host, port, dbname)
        params = dict(host=host, port=port, user=user, password=password,
                      connect_timeout=5, application_name="ddos_lab")
        try:
            self._ensure_database(params, dbname)
            self.conn = psycopg2.connect(dbname=dbname, options=f"-c search_path={SCHEMA},public", **params)
        except (psycopg2.Error, UnicodeDecodeError) as e:
            log.error("Ошибка подключения: %s", safe_str(e))
            raise DbError("Не удалось подключиться к PostgreSQL.\n"
                          "Проверьте, что сервер запущен, а хост, порт, пользователь и пароль указаны верно.") from e
        log.info("Подключение установлено")

    # Создание БД при отсутствии
    def _ensure_database(self, params, dbname):
        conn = psycopg2.connect(dbname="postgres", **params)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
                if cur.fetchone() is None:
                    cur.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8'").format(sql.Identifier(dbname)))
                    log.info("DDL: CREATE DATABASE %s", dbname)
        finally:
            conn.close()

    # Отключение
    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None
            log.info("Соединение закрыто")

    @property
    def connected(self):
        return self.conn is not None and self.conn.closed == 0

    def _require(self):
        if not self.connected:
            raise DbError("Нет подключения к БД. Нажмите «Подключиться».")

    def _rollback(self):
        try:
            self.conn.rollback()
            log.info("ROLLBACK выполнен")
        except psycopg2.Error:
            pass

    # Обёртка транзакции
    @contextmanager
    def transaction(self, action, op="insert"):
        self._require()
        try:
            with self.conn.cursor() as cur:
                yield cur
            self.conn.commit()
            if op != "select":
                log.info("COMMIT: %s", action)
        except psycopg2.Error as e:
            self._rollback()
            code = getattr(e, "pgcode", None) or "-"
            log.error("%s: [%s] %s", action, code, safe_str(e))
            raise DbError(human_error(e, op)) from e

    # Выборка
    def fetch(self, query, params=None):
        with self.transaction("SELECT", op="select") as cur:
            cur.execute(query, params)
            return cur.fetchall(), [c.name for c in cur.description]

    # Текст запроса для показа
    def preview(self, query, params=None):
        self._require()
        with self.conn.cursor() as cur:
            return cur.mogrify(query, params).decode("utf-8")

    # Выполнение собранного запроса
    def run_query(self, query, params=None):
        text = self.preview(query, params)
        log.info("SELECT: %s", " ".join(text.split()))
        return self.fetch(query, params) + (text,)

    # Таблицы схемы
    def tables(self):
        rows, _ = self.fetch("SELECT table_name FROM information_schema.tables "
                             "WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY table_name", (SCHEMA,))
        return [r[0] for r in rows]

    # Таблицы и представления для выборок
    def selectables(self):
        rows, _ = self.fetch(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relkind IN ('r', 'v', 'm') "
            "ORDER BY CASE c.relkind WHEN 'r' THEN 0 WHEN 'v' THEN 1 ELSE 2 END, c.relname", (SCHEMA,))
        return [r[0] for r in rows]

    # Представления схемы
    def views(self):
        rows, _ = self.fetch(
            "SELECT c.relname, CASE c.relkind WHEN 'v' THEN 'VIEW' ELSE 'MATERIALIZED VIEW' END, "
            "(SELECT count(*) FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped), "
            "CASE WHEN c.relkind = 'v' THEN 'вычисляется при каждом запросе' "
            "WHEN c.relispopulated THEN 'хранит снимок данных' ELSE 'не заполнено (нужен REFRESH)' END, "
            "pg_get_viewdef(c.oid, true) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relkind IN ('v', 'm') ORDER BY 2, 1", (SCHEMA,))
        return rows

    def _regclass(self, table):
        return sql.Identifier(SCHEMA, table).as_string(self.conn)

    # Столбцы таблицы
    def columns(self, table):
        rows, _ = self.fetch(
            "SELECT a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull, "
            "coalesce(pg_get_expr(d.adbin, d.adrelid), CASE WHEN a.attidentity <> '' THEN 'IDENTITY' END) "
            "FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
            "WHERE a.attrelid = to_regclass(%s) AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum",
            (self._regclass(table),),
        )
        return rows

    def column_names(self, table):
        return [c[0] for c in self.columns(table)]

    # Ограничения таблицы
    def constraints(self, table):
        rows, _ = self.fetch(
            "SELECT conname, CASE contype WHEN 'p' THEN 'PRIMARY KEY' WHEN 'f' THEN 'FOREIGN KEY' "
            "WHEN 'u' THEN 'UNIQUE' WHEN 'c' THEN 'CHECK' WHEN 'n' THEN 'NOT NULL' ELSE contype::text END, "
            "pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = to_regclass(%s) "
            "ORDER BY position(contype::text in 'pfucn'), conname",
            (self._regclass(table),),
        )
        return rows

    # Внешние ключи схемы
    def foreign_keys(self):
        rows, _ = self.fetch(
            "SELECT cl.relname, a.attname, rcl.relname, ra.attname FROM pg_constraint c "
            "JOIN pg_class cl ON cl.oid = c.conrelid JOIN pg_namespace n ON n.oid = cl.relnamespace "
            "JOIN pg_class rcl ON rcl.oid = c.confrelid "
            "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] "
            "JOIN pg_attribute ra ON ra.attrelid = c.confrelid AND ra.attnum = c.confkey[1] "
            "WHERE c.contype = 'f' AND n.nspname = %s",
            (SCHEMA,),
        )
        return rows

    # Пользовательские типы
    def user_types(self):
        rows, _ = self.fetch(
            "SELECT t.typname, "
            "CASE t.typtype WHEN 'e' THEN 'ENUM' WHEN 'c' THEN 'Составной' ELSE 'DOMAIN' END, "
            "CASE t.typtype "
            " WHEN 'e' THEN (SELECT string_agg(e.enumlabel, ', ' ORDER BY e.enumsortorder) FROM pg_enum e WHERE e.enumtypid = t.oid) "
            " WHEN 'c' THEN (SELECT string_agg(a.attname || ' ' || format_type(a.atttypid, a.atttypmod), ', ' ORDER BY a.attnum) "
            "   FROM pg_attribute a WHERE a.attrelid = t.typrelid AND a.attnum > 0 AND NOT a.attisdropped) "
            " ELSE format_type(t.typbasetype, t.typtypmod) || CASE WHEN t.typnotnull THEN ' NOT NULL' ELSE '' END "
            "   || coalesce(' ' || (SELECT string_agg(pg_get_constraintdef(c.oid), ' ') FROM pg_constraint c WHERE c.contypid = t.oid), '') "
            "END, "
            "coalesce((SELECT string_agg(DISTINCT cl.relname || '.' || a.attname, ', ') FROM pg_attribute a "
            "  JOIN pg_class cl ON cl.oid = a.attrelid WHERE a.atttypid IN (t.oid, t.typarray) "
            "  AND cl.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped), '—') "
            "FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
            "LEFT JOIN pg_class rc ON rc.oid = t.typrelid "
            "WHERE n.nspname = %s AND (t.typtype IN ('e', 'd') OR (t.typtype = 'c' AND rc.relkind = 'c')) "
            "ORDER BY 2, 1",
            (SCHEMA,),
        )
        return rows

    def user_type_names(self):
        return [r[0] for r in self.user_types()]

    # Поля составных типов
    def composite_fields(self):
        rows, _ = self.fetch(
            "SELECT t.typname, a.attname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
            "JOIN pg_class rc ON rc.oid = t.typrelid AND rc.relkind = 'c' "
            "JOIN pg_attribute a ON a.attrelid = t.typrelid AND a.attnum > 0 AND NOT a.attisdropped "
            "WHERE n.nspname = %s ORDER BY t.typname, a.attnum",
            (SCHEMA,),
        )
        out = {}
        for typ, attr in rows:
            out.setdefault(typ, []).append(attr)
        return out

    # Значения ENUM по имени типа
    def enum_labels(self, type_name):
        rows, _ = self.fetch(
            "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
            "JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = %s AND t.typname = %s "
            "ORDER BY e.enumsortorder",
            (SCHEMA, type_name),
        )
        return [r[0] for r in rows]

    # DML из конструктора
    def execute(self, statement, action):
        text = self.preview(statement)
        with self.transaction(f"{action}: {text}") as cur:
            cur.execute(statement)
        return text

    # ALTER TABLE
    def alter(self, statement):
        text = self.preview(statement)
        with self.transaction(f"DDL: {text}", op="ddl") as cur:
            cur.execute(statement)
        return text

    # Создание схемы и таблиц
    def create_schema(self):
        script = SCHEMA_FILE.read_text(encoding="utf-8")
        with self.transaction("DDL: schema.sql (CREATE SCHEMA/TYPE/TABLE)", op="ddl") as cur:
            cur.execute(script)

    # Значения ENUM
    def enum_values(self, type_name):
        rows, _ = self.fetch(
            sql.SQL("SELECT unnest(enum_range(NULL::{}))::text").format(sql.Identifier(SCHEMA, type_name))
        )
        return [r[0] for r in rows]

    # Справочники для выпадающих списков
    def list_models(self):
        return self.fetch("SELECT model_id, name || ' v' || version FROM models ORDER BY name")[0]

    def list_datasets(self):
        return self.fetch("SELECT dataset_id, name FROM datasets ORDER BY name")[0]

    def list_experiments(self):
        return self.fetch("SELECT e.experiment_id, e.title || ' — ' || m.name FROM experiments e "
                          "JOIN models m ON m.model_id = e.model_id ORDER BY e.title")[0]

    # Добавление модели
    def add_model(self, name, family, version, is_production, tags):
        with self.transaction(f"INSERT models ({name})") as cur:
            cur.execute(
                "INSERT INTO models (name, family, version, is_production, tags) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING model_id",
                (name, family, version, is_production, tags),
            )
            return cur.fetchone()[0]

    # Добавление датасета
    def add_dataset(self, name, source, attack_types, records, collected_on):
        with self.transaction(f"INSERT datasets ({name})") as cur:
            cur.execute(
                "INSERT INTO datasets (name, source, attack_types, records, collected_on) "
                "VALUES (%s, %s, %s::ddos_ai.attack_type[], %s, %s) RETURNING dataset_id",
                (name, source, attack_types, records, collected_on),
            )
            return cur.fetchone()[0]

    # Добавление эксперимента
    def add_experiment(self, title, model_id, dataset_id, target_attack, started_on, description):
        with self.transaction(f"INSERT experiments ({title})") as cur:
            cur.execute(
                "INSERT INTO experiments (title, model_id, dataset_id, target_attack, started_on, description) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING experiment_id",
                (title, model_id, dataset_id, target_attack, started_on, description),
            )
            return cur.fetchone()[0]

    # Добавление запуска
    def add_run(self, experiment_id, run_no, status, started_at, precision, recall, f1,
                latency_ms, epochs, gpu_used, feature_set):
        with self.transaction(f"INSERT runs (experiment {experiment_id}, run {run_no})") as cur:
            cur.execute(
                "INSERT INTO runs (experiment_id, run_no, status, started_at, precision_score, recall_score, "
                "f1_score, latency_ms, epochs, gpu_used, feature_set) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING run_id",
                (experiment_id, run_no, status, started_at, precision, recall, f1,
                 latency_ms, epochs, gpu_used, feature_set),
            )
            return cur.fetchone()[0]

    # Сводная таблица с фильтрами
    def report(self, attack=None, status=None, family=None, date_from=None, date_to=None, min_f1=None):
        where, params = [], []
        if attack:
            where.append("e.target_attack = %s")
            params.append(attack)
        if status:
            where.append("r.status = %s")
            params.append(status)
        if family:
            where.append("m.family = %s")
            params.append(family)
        if date_from:
            where.append("r.started_at::date >= %s")
            params.append(date_from)
        if date_to:
            where.append("r.started_at::date <= %s")
            params.append(date_to)
        if min_f1 is not None:
            where.append("r.f1_score >= %s")
            params.append(min_f1)
        query = (
            "SELECT r.run_id AS \"ID\", e.title AS \"Эксперимент\", m.name AS \"Модель\", "
            "m.family::text AS \"Семейство\", coalesce(d.name, '—') AS \"Датасет\", "
            "e.target_attack::text AS \"Атака\", r.run_no AS \"№\", r.status::text AS \"Статус\", "
            "to_char(r.started_at, 'YYYY-MM-DD HH24:MI') AS \"Запуск\", r.precision_score AS \"Precision\", "
            "r.recall_score AS \"Recall\", r.f1_score AS \"F1\", r.latency_ms AS \"Задержка, мс\", "
            "r.epochs AS \"Эпохи\", CASE WHEN r.gpu_used THEN 'да' ELSE 'нет' END AS \"GPU\", "
            "array_to_string(r.feature_set, ', ') AS \"Признаки\" "
            "FROM runs r "
            "JOIN experiments e ON e.experiment_id = r.experiment_id "
            "JOIN models m ON m.model_id = e.model_id "
            "LEFT JOIN datasets d ON d.dataset_id = e.dataset_id"
        )
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY r.started_at DESC, r.run_id"
        log.info("SELECT: сводная таблица runs/experiments/models/datasets, фильтры: %s", " AND ".join(where) or "нет")
        return self.fetch(query, params)

    # Демо-данные
    def seed_demo(self):
        models = [
            ("RF-NetFlow", "random_forest", "1.2", True, ["baseline", "netflow"]),
            ("XGB-Edge", "xgboost", "2.0", False, ["edge", "fast"]),
            ("LSTM-Traffic", "lstm", "1.0", False, ["sequence", "gpu"]),
            ("TransDDoS", "transformer", "0.9.1", False, ["attention", "research"]),
            ("GNN-Graph", "gnn", "0.1", False, ["graph", "draft"]),
        ]
        datasets = [
            ("CIC-DDoS2019", "Canadian Institute for Cybersecurity",
             ["syn_flood", "udp_flood", "dns_amplification", "ntp_amplification"], 50063112, "2019-01-12"),
            ("CIC-IDS2017", "Canadian Institute for Cybersecurity",
             ["http_flood", "slowloris", "syn_flood"], 2830743, "2017-07-03"),
            ("Campus-Mirror-2025", "Зеркало трафика вуза", ["mixed", "icmp_flood"], 1250000, "2025-10-01"),
            ("Botnet-Lab-2026", "  Лабораторный стенд  ", ["udp_flood"], 50000, "2026-02-10"),
        ]
        experiments = [
            ("Baseline SYN", "RF-NetFlow", "CIC-DDoS2019", "syn_flood", "2025-09-01", "Базовая модель по NetFlow"),
            ("Amplification", "XGB-Edge", "CIC-DDoS2019", "dns_amplification", "2025-09-15", "Детект на edge-узлах"),
            ("Slow HTTP", "LSTM-Traffic", "CIC-IDS2017", "slowloris", "2025-10-05", "Последовательности пакетов"),
            ("Campus mixed", "TransDDoS", "Campus-Mirror-2025", "mixed", "2025-11-02", "Смешанные атаки"),
            ("Draft ICMP", "RF-NetFlow", None, "icmp_flood", "2025-11-10", "   Черновик без запусков   "),
        ]
        runs = [
            ("Baseline SYN", "RF-NetFlow", 1, "completed", "2025-09-01 10:00", 0.9412, 0.9120, 0.9264, 3.2, 50, False, ["pkt_rate", "syn_ratio"]),
            ("Baseline SYN", "RF-NetFlow", 2, "completed", "2025-09-02 11:30", 0.9550, 0.9301, 0.9424, 3.5, 80, False, ["pkt_rate", "syn_ratio", "ttl"]),
            ("Amplification", "XGB-Edge", 1, "completed", "2025-09-15 09:10", 0.9701, 0.9650, 0.9675, 1.1, 120, False, ["bytes_ratio", "src_port", "dns_qtype"]),
            ("Amplification", "XGB-Edge", 2, "failed", "2025-09-16 14:00", None, None, None, None, 120, True, ["bytes_ratio"]),
            ("Slow HTTP", "LSTM-Traffic", 1, "completed", "2025-10-05 18:20", 0.8820, 0.9015, 0.8916, 12.7, 30, True, ["iat_mean", "conn_duration"]),
            ("Slow HTTP", "LSTM-Traffic", 2, "running", "2025-10-07 08:45", None, None, None, None, 60, True, ["iat_mean", "conn_duration", "hdr_len"]),
            ("Campus mixed", "TransDDoS", 1, "completed", "2025-11-02 12:00", 0.9833, 0.9710, 0.9771, 8.4, 40, True, ["flow_embed", "entropy_src"]),
            ("Campus mixed", "TransDDoS", 2, "queued", "2025-11-03 12:00", None, None, None, None, 40, True, ["flow_embed"]),
        ]
        with self.transaction("INSERT демо-данные") as cur:
            model_ids, dataset_ids, exp_ids = {}, {}, {}
            for m in models:
                cur.execute("INSERT INTO models (name, family, version, is_production, tags) "
                            "VALUES (%s, %s, %s, %s, %s) RETURNING model_id", m)
                model_ids[m[0]] = cur.fetchone()[0]
            for d in datasets:
                cur.execute("INSERT INTO datasets (name, source, attack_types, records, collected_on) "
                            "VALUES (%s, %s, %s::ddos_ai.attack_type[], %s, %s) RETURNING dataset_id", d)
                dataset_ids[d[0]] = cur.fetchone()[0]
            for title, model, dataset, attack, started, descr in experiments:
                cur.execute("INSERT INTO experiments (title, model_id, dataset_id, target_attack, started_on, description) "
                            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING experiment_id",
                            (title, model_ids[model], dataset_ids.get(dataset), attack, started, descr))
                exp_ids[(title, model)] = cur.fetchone()[0]
            for title, model, *rest in runs:
                cur.execute("INSERT INTO runs (experiment_id, run_no, status, started_at, precision_score, recall_score, "
                            "f1_score, latency_ms, epochs, gpu_used, feature_set) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                            (exp_ids[(title, model)], *rest))

    # Проверка ссылочной целостности
    def integrity_check(self):
        self._require()
        results = []
        cur = self.conn.cursor()
        log.info("Проверка ссылочной целостности: начало")

        def attempt(name, statement, params=None, op="insert", after=None):
            cur.execute("SAVEPOINT sp")
            try:
                cur.execute(statement, params)
                text = after() if after else f"выполнено, затронуто строк: {cur.rowcount}"
                results.append((name, True, text))
            except psycopg2.Error as e:
                log.info("Ожидаемая ошибка (%s): [%s] %s", name, e.pgcode, safe_str(e))
                results.append((name, False, human_error(e, op)))
            cur.execute("ROLLBACK TO SAVEPOINT sp")

        def count(query, params=None):
            cur.execute(query, params)
            return cur.fetchone()[0]

        try:
            cur.execute("SELECT e.experiment_id, e.model_id, e.dataset_id, "
                        "(SELECT count(*) FROM runs r WHERE r.experiment_id = e.experiment_id) "
                        "FROM experiments e ORDER BY 4 DESC LIMIT 1")
            row = cur.fetchone()
            if row is None:
                raise DbError("Нет данных для проверки. Сначала внесите данные или добавьте демо-данные.")
            exp_id, model_id, dataset_id, runs_cnt = row

            attempt("INSERT эксперимента с несуществующей моделью (model_id = -1)",
                    "INSERT INTO experiments (title, model_id, target_attack) VALUES ('Orphan', -1, 'mixed')")
            attempt("INSERT запуска для несуществующего эксперимента",
                    "INSERT INTO runs (experiment_id, run_no, feature_set) VALUES (-1, 1, ARRAY['x'])")
            attempt(f"DELETE модели {model_id}, на которую ссылается эксперимент (ON DELETE RESTRICT)",
                    "DELETE FROM models WHERE model_id = %s", (model_id,), op="delete")
            attempt(f"UPDATE model_id {model_id} → {model_id + 1000} (ON UPDATE CASCADE)",
                    "UPDATE models SET model_id = model_id + 1000 WHERE model_id = %s", (model_id,),
                    after=lambda: f"разрешено: в experiments model_id обновлён у "
                                  f"{count('SELECT count(*) FROM experiments WHERE model_id = %s', (model_id + 1000,))} строк")
            attempt(f"DELETE эксперимента {exp_id} с {runs_cnt} запусками (ON DELETE CASCADE)",
                    "DELETE FROM experiments WHERE experiment_id = %s", (exp_id,), op="delete",
                    after=lambda: f"разрешено: каскадно удалено запусков — "
                                  f"{runs_cnt - count('SELECT count(*) FROM runs WHERE experiment_id = %s', (exp_id,))}")
            if dataset_id is not None:
                attempt(f"DELETE датасета {dataset_id} (ON DELETE SET NULL)",
                        "DELETE FROM datasets WHERE dataset_id = %s", (dataset_id,), op="delete",
                        after=lambda: f"разрешено: у экспериментов dataset_id стал NULL — "
                                      f"{count('SELECT count(*) FROM experiments WHERE experiment_id = %s AND dataset_id IS NULL', (exp_id,))} строк")
            attempt("INSERT запуска с повторным номером (UNIQUE)",
                    "INSERT INTO runs (experiment_id, run_no, feature_set) "
                    "SELECT experiment_id, run_no, ARRAY['x'] FROM runs LIMIT 1")
        except psycopg2.Error as e:
            self._rollback()
            log.error("Проверка целостности: [%s] %s", getattr(e, "pgcode", "-"), safe_str(e))
            raise DbError(human_error(e)) from e
        except DbError:
            self._rollback()
            raise
        finally:
            cur.close()
        self._rollback()
        log.info("Проверка ссылочной целостности: завершена, изменения отменены (ROLLBACK)")
        return results
