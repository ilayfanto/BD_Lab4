import re

from psycopg2 import sql

from db import SCHEMA, DbError

I = sql.Identifier
L = sql.Literal

NAME_RE = re.compile(r"^[^\W\d]\w{0,62}$")
TYPE_RE = re.compile(r"^[^\W\d][\w ]*(\(\s*\d+\s*(,\s*\d+\s*)?\))?(\[\])?$")

FK_ACTIONS = ["NO ACTION", "RESTRICT", "CASCADE", "SET NULL", "SET DEFAULT"]
AGG_FUNCS = ["COUNT", "SUM", "AVG", "MIN", "MAX", "STRING_AGG"]
COMPARE_OPS = ["=", "<>", "<", ">", "<=", ">="]
TEXT_OPS = ["LIKE", "ILIKE", "NOT LIKE", "~", "~*", "!~", "!~*", "SIMILAR TO", "NOT SIMILAR TO"]
WHERE_OPS = COMPARE_OPS + TEXT_OPS + ["IN", "IS NULL", "IS NOT NULL"]
JOIN_TYPES = ["INNER JOIN", "LEFT JOIN", "RIGHT JOIN", "FULL JOIN", "CROSS JOIN"]
DIRECTIONS = ["ASC", "DESC"]

ALTER_OPS = [
    ("add_column", "Добавить столбец (ADD COLUMN)"),
    ("drop_column", "Удалить столбец (DROP COLUMN)"),
    ("rename_column", "Переименовать столбец (RENAME COLUMN)"),
    ("rename_table", "Переименовать таблицу (RENAME TO)"),
    ("alter_type", "Изменить тип данных (ALTER COLUMN TYPE)"),
    ("set_not_null", "Задать NOT NULL"),
    ("drop_not_null", "Убрать NOT NULL"),
    ("set_default", "Задать значение по умолчанию (SET DEFAULT)"),
    ("drop_default", "Убрать значение по умолчанию (DROP DEFAULT)"),
    ("add_check", "Добавить CHECK"),
    ("add_unique", "Добавить UNIQUE"),
    ("add_fk", "Добавить FOREIGN KEY"),
    ("drop_constraint", "Удалить ограничение (DROP CONSTRAINT)"),
]


# Проверка имени
def check_name(name, what):
    if not name or not NAME_RE.match(name):
        raise DbError(f"Недопустимое {what}: «{name or ''}». Используйте буквы, цифры и _, начиная с буквы.")
    return name


# Проверка типа данных
def check_type(typ):
    typ = (typ or "").strip()
    if not TYPE_RE.match(typ):
        raise DbError(f"Недопустимый тип данных: «{typ}». Пример: varchar(50), numeric(6,2), text[].")
    return typ


def need(value, what, strip=True):
    text = "" if value is None else str(value)
    if (text.strip() if strip else text) == "":
        raise DbError(f"Не заполнено поле «{what}».")
    return text.strip() if strip else text


# Построение ALTER TABLE
def build_alter(op, table, p):
    head = sql.SQL("ALTER TABLE {} ").format(I(SCHEMA, table))
    col = lambda: I(need(p.get("column"), "Столбец"))
    if op == "add_column":
        body = sql.SQL("ADD COLUMN {} {}").format(I(check_name(p.get("name"), "имя столбца")),
                                                  sql.SQL(check_type(p.get("type"))))
        if p.get("default"):
            body += sql.SQL(" DEFAULT {}").format(L(p["default"]))
        if p.get("not_null"):
            body += sql.SQL(" NOT NULL")
    elif op == "drop_column":
        body = sql.SQL("DROP COLUMN {}").format(col())
        if p.get("cascade"):
            body += sql.SQL(" CASCADE")
    elif op == "rename_column":
        body = sql.SQL("RENAME COLUMN {} TO {}").format(col(), I(check_name(p.get("name"), "новое имя столбца")))
    elif op == "rename_table":
        body = sql.SQL("RENAME TO {}").format(I(check_name(p.get("name"), "новое имя таблицы")))
    elif op == "alter_type":
        typ = sql.SQL(check_type(p.get("type")))
        body = sql.SQL("ALTER COLUMN {} TYPE {}").format(col(), typ)
        if p.get("using"):
            body += sql.SQL(" USING {}::{}").format(col(), typ)
    elif op == "set_not_null":
        body = sql.SQL("ALTER COLUMN {} SET NOT NULL").format(col())
    elif op == "drop_not_null":
        body = sql.SQL("ALTER COLUMN {} DROP NOT NULL").format(col())
    elif op == "set_default":
        body = sql.SQL("ALTER COLUMN {} SET DEFAULT {}").format(col(), L(need(p.get("default"), "Значение")))
    elif op == "drop_default":
        body = sql.SQL("ALTER COLUMN {} DROP DEFAULT").format(col())
    elif op == "add_check":
        expr = need(p.get("expr"), "Условие CHECK")
        if ";" in expr:
            raise DbError("Условие CHECK не должно содержать «;».")
        body = sql.SQL("ADD CONSTRAINT {} CHECK ({})").format(I(check_name(p.get("name"), "имя ограничения")),
                                                              sql.SQL(expr))
    elif op == "add_unique":
        cols = p.get("columns") or []
        if not cols:
            raise DbError("Выберите хотя бы один столбец для UNIQUE.")
        body = sql.SQL("ADD CONSTRAINT {} UNIQUE ({})").format(I(check_name(p.get("name"), "имя ограничения")),
                                                               sql.SQL(", ").join(map(I, cols)))
    elif op == "add_fk":
        on_delete, on_update = p.get("on_delete", "NO ACTION"), p.get("on_update", "NO ACTION")
        if on_delete not in FK_ACTIONS or on_update not in FK_ACTIONS:
            raise DbError("Недопустимое действие ON DELETE / ON UPDATE.")
        body = sql.SQL("ADD CONSTRAINT {} FOREIGN KEY ({}) REFERENCES {} ({}) ON DELETE {} ON UPDATE {}").format(
            I(check_name(p.get("name"), "имя ограничения")), col(),
            I(SCHEMA, need(p.get("ref_table"), "Таблица-родитель")), I(need(p.get("ref_column"), "Столбец-родитель")),
            sql.SQL(on_delete), sql.SQL(on_update))
    elif op == "drop_constraint":
        body = sql.SQL("DROP CONSTRAINT {}").format(I(need(p.get("constraint"), "Ограничение")))
        if p.get("cascade"):
            body += sql.SQL(" CASCADE")
    else:
        raise DbError(f"Неизвестная операция: {op}")
    return head + body


# Имя столбца, возможно с псевдонимом таблицы
def ident(column):
    return I(*column) if isinstance(column, tuple) else I(column)


# Условие WHERE
def condition(column, op, value):
    if op not in WHERE_OPS:
        raise DbError(f"Недопустимый оператор: {op}")
    c = ident(column)
    if op in ("IS NULL", "IS NOT NULL"):
        return sql.SQL("{} " + op).format(c)
    if op == "IN":
        items = [v.strip() for v in (value or "").split(",") if v.strip()]
        if not items:
            raise DbError(f"Для IN укажите значения через запятую (столбец «{column}»).")
        return sql.SQL("{}::text = ANY({})").format(c, L(items))
    if op in TEXT_OPS:
        return sql.SQL("{}::text " + op + " {}").format(c, L(value or ""))
    return sql.SQL("{} " + op + " {}").format(c, L(value))


# Агрегатное выражение
def aggregate(func, column):
    if func not in AGG_FUNCS:
        raise DbError(f"Недопустимая функция: {func}")
    if column == "*":
        if func != "COUNT":
            raise DbError(f"{func}(*) не поддерживается — выберите столбец.")
        return sql.SQL("COUNT(*)")
    if func == "STRING_AGG":
        return sql.SQL("STRING_AGG({}::text, ', ')").format(ident(column))
    return sql.SQL(func + "({})").format(ident(column))


GROUPING_MODES = [
    ("plain", "GROUP BY — обычная группировка"),
    ("rollup", "ROLLUP — подитоги по иерархии + общий итог"),
    ("cube", "CUBE — все комбинации столбцов + общий итог"),
    ("sets", "GROUPING SETS — свои наборы группировок"),
]
TOTAL_LABEL = "ИТОГО"


# Источник: таблица схемы или CTE
def source(table, cte_names=()):
    return I(table) if table in cte_names else I(SCHEMA, table)


def _grouping_clause(grouping, group_by, grouping_sets):
    if grouping == "plain":
        return sql.SQL(", ").join(map(I, group_by)) if group_by else None
    if grouping in ("rollup", "cube"):
        if not group_by:
            raise DbError("Отметьте столбцы в GROUP BY — по ним будет построен " + grouping.upper() + ".")
        return sql.SQL(grouping.upper() + " ({})").format(sql.SQL(", ").join(map(I, group_by)))
    if grouping == "sets":
        if not grouping_sets:
            raise DbError("Добавьте хотя бы один набор для GROUPING SETS.")
        sets = [sql.SQL("({})").format(sql.SQL(", ").join(map(I, s))) for s in grouping_sets]
        return sql.SQL("GROUPING SETS ({})").format(sql.SQL(", ").join(sets))
    raise DbError(f"Неизвестный режим группировки: {grouping}")


# Конструктор SELECT
def build_select(table, columns, aggregates=(), where=(), where_join="AND", group_by=(),
                 having=(), order_by=(), limit=0, computed=(), grouping="plain", grouping_sets=(),
                 label_totals=False, show_grouping=False, cte_names=()):
    if grouping == "sets":
        grouped = []
        for s in grouping_sets:
            grouped += [c for c in s if c not in grouped]
    else:
        grouped = list(group_by)
    computed_names = [a for a, _ in computed]
    real_grouped = [c for c in grouped if c not in computed_names]
    items = []
    for c in columns:
        if label_totals and grouping != "plain" and c in real_grouped:
            items.append(sql.SQL("CASE WHEN GROUPING({c}) = 1 THEN {t} ELSE {c}::text END AS {c}").format(
                c=I(c), t=L(TOTAL_LABEL)))
        else:
            items.append(I(c))
    items += [sql.SQL("{} AS {}").format(expr, I(alias)) for alias, expr in computed]
    for func, column, alias in aggregates:
        alias = alias or f"{func.lower()}_{'all' if column == '*' else column}"
        items.append(sql.SQL("{} AS {}").format(aggregate(func, column), I(alias)))
    if show_grouping and grouping != "plain" and real_grouped:
        items.append(sql.SQL("GROUPING({}) AS {}").format(sql.SQL(", ").join(map(I, real_grouped)), I("grouping_level")))
    if not items:
        raise DbError("Выберите хотя бы один столбец или агрегатную функцию.")
    q = sql.SQL("SELECT {} FROM {}").format(sql.SQL(", ").join(items), source(table, cte_names))
    if where:
        joiner = sql.SQL(" AND " if where_join == "AND" else " OR ")
        q += sql.SQL(" WHERE ") + joiner.join(condition(*w) for w in where)
    clause = _grouping_clause(grouping, group_by, grouping_sets)
    if clause is not None:
        q += sql.SQL(" GROUP BY ") + clause
    if having:
        parts = []
        for func, column, op, value in having:
            if op not in COMPARE_OPS:
                raise DbError(f"Недопустимый оператор HAVING: {op}")
            parts.append(sql.SQL("{} " + op + " {}").format(aggregate(func, column), L(need(value, "Значение HAVING"))))
        q += sql.SQL(" HAVING ") + sql.SQL(" AND ").join(parts)
    if order_by:
        parts = []
        for field, direction in order_by:
            if direction not in DIRECTIONS:
                raise DbError(f"Недопустимое направление сортировки: {direction}")
            parts.append(sql.SQL("{} " + direction + " NULLS LAST").format(I(need(field, "Поле ORDER BY"))))
        q += sql.SQL(" ORDER BY ") + sql.SQL(", ").join(parts)
    if limit:
        q += sql.SQL(" LIMIT {}").format(L(int(limit)))
    return q


# Мастер JOIN
def build_join(base, steps, columns, limit=1000):
    tables = [base] + [s[1] for s in steps]
    repeated = {t for t in tables if tables.count(t) > 1}
    items = []
    for n, table in enumerate(tables, 1):
        alias = f"t{n}"
        for c in columns[table]:
            label = f"{alias}.{c}" if table in repeated else f"{table}.{c}"
            items.append(sql.SQL("{}.{} AS {}").format(I(alias), I(c), I(label)))
    q = sql.SQL("SELECT {} FROM {} AS t1").format(sql.SQL(", ").join(items), I(SCHEMA, base))
    for n, (join_type, table, left, right) in enumerate(steps, 2):
        if join_type not in JOIN_TYPES:
            raise DbError(f"Недопустимый тип соединения: {join_type}")
        q += sql.SQL(" " + join_type + " {} AS {}").format(I(SCHEMA, table), I(f"t{n}"))
        if join_type != "CROSS JOIN":
            if not left or not right:
                raise DbError(f"Для соединения с «{table}» выберите поля связи.")
            q += sql.SQL(" ON {}.{} = {}.{}").format(I(left[0]), I(left[1]), I(f"t{n}"), I(right))
    return q + sql.SQL(" LIMIT {}").format(L(limit))


STRING_FUNCS = [
    ("UPPER", "UPPER — верхний регистр", ()),
    ("LOWER", "LOWER — нижний регистр", ()),
    ("INITCAP", "INITCAP — Каждое Слово С Заглавной", ()),
    ("LENGTH", "LENGTH — длина строки", ()),
    ("TRIM", "TRIM — убрать пробелы/символы по краям", ("Символы (необязательно)",)),
    ("LTRIM", "LTRIM — убрать слева", ("Символы (необязательно)",)),
    ("RTRIM", "RTRIM — убрать справа", ("Символы (необязательно)",)),
    ("SUBSTRING", "SUBSTRING — подстрока по позиции", ("С позиции", "Длина (необязательно)")),
    ("SUBSTRING_RE", "SUBSTRING — подстрока по регулярке", ("Регулярное выражение",)),
    ("POSITION", "POSITION — позиция подстроки", ("Подстрока",)),
    ("REPLACE", "REPLACE — замена", ("Что заменить", "На что")),
    ("LPAD", "LPAD — дополнить слева", ("Итоговая длина", "Символ заполнения")),
    ("RPAD", "RPAD — дополнить справа", ("Итоговая длина", "Символ заполнения")),
    ("CONCAT", "CONCAT — объединить", ("Разделитель", "Текст (если нет 2-го столбца)")),
    ("PIPES", "|| — объединить оператором", ("Разделитель", "Текст (если нет 2-го столбца)")),
]


# Выражение строковой функции
def string_expr(func, x, p1="", p2="", y=None):
    if func in ("UPPER", "LOWER", "INITCAP", "LENGTH"):
        return sql.SQL(func + "({})").format(x)
    if func == "TRIM":
        return sql.SQL("TRIM(BOTH {} FROM {})").format(L(p1), x) if p1 else sql.SQL("TRIM({})").format(x)
    if func in ("LTRIM", "RTRIM"):
        return sql.SQL(func + "({}, {})").format(x, L(p1)) if p1 else sql.SQL(func + "({})").format(x)
    if func == "SUBSTRING":
        start = L(need(p1, "С позиции"))
        if p2:
            return sql.SQL("SUBSTRING({} FROM {}::int FOR {}::int)").format(x, start, L(p2))
        return sql.SQL("SUBSTRING({} FROM {}::int)").format(x, start)
    if func == "SUBSTRING_RE":
        return sql.SQL("SUBSTRING({} FROM {}::text)").format(x, L(need(p1, "Регулярное выражение")))
    if func == "POSITION":
        return sql.SQL("POSITION({}::text IN {})").format(L(need(p1, "Подстрока", strip=False)), x)
    if func == "REPLACE":
        return sql.SQL("REPLACE({}, {}, {})").format(x, L(need(p1, "Что заменить", strip=False)), L(p2))
    if func in ("LPAD", "RPAD"):
        length = L(need(p1, "Итоговая длина"))
        if p2:
            return sql.SQL(func + "({}, {}::int, {})").format(x, length, L(p2))
        return sql.SQL(func + "({}, {}::int)").format(x, length)
    if func in ("CONCAT", "PIPES"):
        other = y if y is not None else L(p2)
        if func == "CONCAT":
            return sql.SQL("CONCAT({}, {}, {})").format(x, L(p1), other)
        return sql.SQL("{} || {} || {}").format(x, L(p1), other)
    raise DbError(f"Неизвестная функция: {func}")


def _source(table, column, literal):
    if table:
        return sql.SQL("{}::text").format(I(column)), sql.SQL(" FROM {} LIMIT 200").format(I(SCHEMA, table))
    return L(literal), sql.SQL("")


# Запрос строковой функции
def build_string(func, table=None, column=None, literal="", p1="", p2="", column2=None):
    x, tail = _source(table, column, literal)
    y = sql.SQL("{}::text").format(I(column2)) if (table and column2) else None
    expr = string_expr(func, x, p1, p2, y)
    return sql.SQL("SELECT {x} AS {a}, {e} AS {b}, LENGTH({x}) AS {c}, LENGTH(({e})::text) AS {d}").format(
        x=x, e=expr, a=I("Исходное"), b=I("Результат"), c=I("Длина до"), d=I("Длина после")) + tail


# Все строковые функции сразу
def build_all_strings(table=None, column=None, literal=""):
    x, tail = _source(table, column, literal)
    demo = [
        ("UPPER", string_expr("UPPER", x)),
        ("LOWER", string_expr("LOWER", x)),
        ("INITCAP", string_expr("INITCAP", x)),
        ("LENGTH", string_expr("LENGTH", x)),
        ("TRIM", string_expr("TRIM", x)),
        ("SUBSTRING(1,5)", string_expr("SUBSTRING", x, "1", "5")),
        ("POSITION(' ')", string_expr("POSITION", x, " ")),
        ("REPLACE(' ','_')", string_expr("REPLACE", x, " ", "_")),
        ("LPAD(25,'*')", string_expr("LPAD", x, "25", "*")),
        ("RPAD(25,'.')", string_expr("RPAD", x, "25", ".")),
        ("CONCAT('[',x,']')", sql.SQL("CONCAT('[', {}, ']')").format(x)),
        ("x || ' #DDoS'", sql.SQL("{} || ' #DDoS'").format(x)),
    ]
    items = [sql.SQL("{} AS {}").format(x, I("Исходное"))]
    items += [sql.SQL("{} AS {}").format(e, I(name)) for name, e in demo]
    return sql.SQL("SELECT ") + sql.SQL(", ").join(items) + tail


# Проверка строки на шаблон
def build_match_test(text, op, pattern):
    if op not in TEXT_OPS:
        raise DbError(f"Недопустимый оператор: {op}")
    return sql.SQL("SELECT {} " + op + " {}").format(L(text), L(pattern))


def _as_text(column, as_text):
    return sql.SQL("{}::text").format(ident(column)) if as_text else ident(column)


# Выражение CASE
def case_expr(whens, else_value=None):
    if not whens:
        raise DbError("Добавьте хотя бы одно условие WHEN … THEN.")
    parts = []
    for column, op, value, result in whens:
        parts.append(sql.SQL("WHEN {} THEN {}").format(condition(column, op, value), L(result)))
    expr = sql.SQL("CASE ") + sql.SQL(" ").join(parts)
    if else_value is not None:
        expr += sql.SQL(" ELSE {}").format(L(else_value))
    return expr + sql.SQL(" END")


# Выражение COALESCE
def coalesce_expr(column, value, column2=None, as_text=False):
    args = [_as_text(column, as_text)]
    if column2:
        args.append(_as_text(column2, as_text))
    args.append(L(value))
    return sql.SQL("COALESCE({})").format(sql.SQL(", ").join(args))


# Выражение NULLIF
def nullif_expr(column, value, as_text=False):
    return sql.SQL("NULLIF({}, {})").format(_as_text(column, as_text), L(value))


SUB_KINDS = [
    ("IN", "IN (подзапрос) — значение входит в список"),
    ("NOT IN", "NOT IN (подзапрос) — значение не входит в список"),
    ("ANY", "оператор ANY (подзапрос) — хотя бы с одним"),
    ("ALL", "оператор ALL (подзапрос) — со всеми"),
    ("EXISTS", "EXISTS (подзапрос) — есть хотя бы одна строка"),
    ("NOT EXISTS", "NOT EXISTS (подзапрос) — нет ни одной строки"),
    ("SCALAR", "оператор (SELECT агрегат …) — скалярный подзапрос"),
]


# Условие с подзапросом
def build_subquery_condition(c):
    kind = c["kind"]
    inner = need(c.get("inner_table"), "Таблица подзапроса")
    if kind in ("EXISTS", "NOT EXISTS"):
        select = sql.SQL("1")
    elif kind == "SCALAR":
        select = aggregate(c.get("agg") or "AVG", ("i", need(c.get("inner_col"), "Столбец подзапроса")))
    else:
        select = I("i", need(c.get("inner_col"), "Столбец подзапроса"))
    where = []
    if c.get("filter_col"):
        where.append(condition(("i", c["filter_col"]), c.get("filter_op") or "=", c.get("filter_val")))
    if c.get("correlated"):
        where.append(sql.SQL("{} = {}").format(I("i", need(c.get("corr_inner"), "Связь: поле подзапроса")),
                                               I("o", need(c.get("corr_outer"), "Связь: поле внешней таблицы"))))
    sub = sql.SQL("SELECT {} FROM {} AS i").format(select, I(SCHEMA, inner))
    if where:
        sub += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(where)
    if kind in ("EXISTS", "NOT EXISTS"):
        return sql.SQL(kind + " ({})").format(sub)
    outer = I("o", need(c.get("outer_col"), "Столбец внешней таблицы"))
    if kind in ("IN", "NOT IN"):
        return sql.SQL("{} " + kind + " ({})").format(outer, sub)
    op = c.get("op") or "="
    if op not in COMPARE_OPS:
        raise DbError(f"Недопустимый оператор: {op}")
    if kind in ("ANY", "ALL"):
        return sql.SQL("{} " + op + " " + kind + " ({})").format(outer, sub)
    if kind == "SCALAR":
        return sql.SQL("{} " + op + " ({})").format(outer, sub)
    raise DbError(f"Неизвестный вид подзапроса: {kind}")


# Выборка с фильтрами-подзапросами
def build_subquery_select(table, conditions, join="AND", limit=1000):
    q = sql.SQL("SELECT o.* FROM {} AS o").format(I(SCHEMA, table))
    if conditions:
        q += sql.SQL(" WHERE ") + sql.SQL(f" {join} ").join(conditions)
    return q + sql.SQL(" LIMIT {}").format(L(limit))


TYPE_KINDS = [("enum", "ENUM (перечисление)"), ("composite", "Составной тип"), ("domain", "DOMAIN (тип с проверкой)")]

TYPE_OPS = [
    ("enum_add", "ENUM: добавить значение"),
    ("enum_rename", "ENUM: переименовать значение"),
    ("attr_add", "Составной: добавить поле"),
    ("attr_drop", "Составной: удалить поле"),
    ("rename", "Переименовать тип"),
    ("drop", "Удалить тип"),
]


# Создание пользовательского типа
def build_create_type(kind, name, values=(), fields=(), base=None, default=None, not_null=False, check=None):
    t = I(SCHEMA, check_name(name, "имя типа"))
    if kind == "enum":
        values = [v for v in values if v != ""]
        if not values:
            raise DbError("Добавьте хотя бы одно значение ENUM.")
        if len(set(values)) != len(values):
            raise DbError("Значения ENUM не должны повторяться.")
        return sql.SQL("CREATE TYPE {} AS ENUM ({})").format(t, sql.SQL(", ").join(map(L, values)))
    if kind == "composite":
        fields = [(f, ft) for f, ft in fields if f or ft]
        if not fields:
            raise DbError("Добавьте хотя бы одно поле составного типа.")
        parts = [sql.SQL("{} {}").format(I(check_name(f, "имя поля")), sql.SQL(check_type(ft))) for f, ft in fields]
        return sql.SQL("CREATE TYPE {} AS ({})").format(t, sql.SQL(", ").join(parts))
    if kind == "domain":
        q = sql.SQL("CREATE DOMAIN {} AS {}").format(t, sql.SQL(check_type(base)))
        if default:
            q += sql.SQL(" DEFAULT {}").format(L(default))
        if not_null:
            q += sql.SQL(" NOT NULL")
        if check:
            if ";" in check:
                raise DbError("Условие CHECK не должно содержать «;».")
            q += sql.SQL(" CHECK ({})").format(sql.SQL(check))
        return q
    raise DbError(f"Неизвестный вид типа: {kind}")


# Изменение пользовательского типа
def build_alter_type(op, type_name, kind, p):
    t = I(SCHEMA, type_name)
    word = sql.SQL("DOMAIN" if kind == "domain" else "TYPE")
    if op == "enum_add":
        q = sql.SQL("ALTER TYPE {} ADD VALUE {}").format(t, L(need(p.get("value"), "Новое значение", strip=False)))
        if p.get("position") in ("BEFORE", "AFTER") and p.get("ref"):
            q += sql.SQL(" " + p["position"] + " {}").format(L(p["ref"]))
        return q
    if op == "enum_rename":
        return sql.SQL("ALTER TYPE {} RENAME VALUE {} TO {}").format(
            t, L(need(p.get("ref"), "Значение")), L(need(p.get("value"), "Новое значение", strip=False)))
    if op == "attr_add":
        return sql.SQL("ALTER TYPE {} ADD ATTRIBUTE {} {}").format(
            t, I(check_name(p.get("name"), "имя поля")), sql.SQL(check_type(p.get("type"))))
    if op == "attr_drop":
        q = sql.SQL("ALTER TYPE {} DROP ATTRIBUTE {}").format(t, I(need(p.get("attr"), "Поле")))
        return q + sql.SQL(" CASCADE") if p.get("cascade") else q
    if op == "rename":
        return sql.SQL("ALTER {} {} RENAME TO {}").format(word, t, I(check_name(p.get("name"), "новое имя типа")))
    if op == "drop":
        q = sql.SQL("DROP {} {}").format(word, t)
        return q + sql.SQL(" CASCADE") if p.get("cascade") else q
    raise DbError(f"Неизвестная операция: {op}")


# Создание таблицы
def build_create_table(name, columns, with_id=True):
    parts = []
    if with_id:
        parts.append(sql.SQL("id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"))
    for col, typ, not_null in columns:
        if not col and not typ:
            continue
        part = sql.SQL("{} {}").format(I(check_name(col, "имя столбца")), sql.SQL(check_type(typ)))
        if not_null:
            part += sql.SQL(" NOT NULL")
        parts.append(part)
    if not parts:
        raise DbError("Добавьте хотя бы один столбец.")
    return sql.SQL("CREATE TABLE {} ({})").format(I(SCHEMA, check_name(name, "имя таблицы")), sql.SQL(", ").join(parts))


# Вставка строки
def build_insert(table, values):
    values = {k: v for k, v in values.items() if v != ""}
    if not values:
        raise DbError("Заполните хотя бы одно поле.")
    return sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        I(SCHEMA, table), sql.SQL(", ").join(map(I, values)), sql.SQL(", ").join(map(L, values.values())))


# Просмотр таблицы с раскрытием составных полей
def build_table_view(table, columns, composite_fields, limit=500):
    items = []
    for col, typ in columns:
        items.append(I(col))
        for field in composite_fields.get(typ, []):
            items.append(sql.SQL("({}).{} AS {}").format(I(col), I(field), I(f"{col}.{field}")))
    return sql.SQL("SELECT {} FROM {} LIMIT {}").format(sql.SQL(", ").join(items), I(SCHEMA, table), L(limit))


# Итоговый запрос CTE
def build_cte_main(src, columns=(), join=None, where=(), order_by=(), limit=0, cte_names=()):
    label = (lambda a, c: f"{a}.{c}") if join else (lambda a, c: c)
    items = [sql.SQL("{}.{} AS {}").format(I(a), I(c), I(label(a, c))) for a, c in columns] or [sql.SQL("*")]
    q = sql.SQL("SELECT {} FROM {} AS a").format(sql.SQL(", ").join(items), source(need(src, "Источник"), cte_names))
    if join:
        join_type, table, left, right = join
        if join_type not in JOIN_TYPES:
            raise DbError(f"Недопустимый тип соединения: {join_type}")
        q += sql.SQL(" " + join_type + " {} AS b").format(source(need(table, "Присоединяемый источник"), cte_names))
        if join_type != "CROSS JOIN":
            q += sql.SQL(" ON {} = {}").format(I("a", need(left, "Поле связи a")), I("b", need(right, "Поле связи b")))
    if where:
        q += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(condition((a, c), op, v) for a, c, op, v in where)
    if order_by:
        parts = []
        for a, c, direction in order_by:
            if direction not in DIRECTIONS:
                raise DbError(f"Недопустимое направление сортировки: {direction}")
            parts.append(sql.SQL("{} " + direction + " NULLS LAST").format(I(a, c)))
        q += sql.SQL(" ORDER BY ") + sql.SQL(", ").join(parts)
    if limit:
        q += sql.SQL(" LIMIT {}").format(L(int(limit)))
    return q


# Запрос WITH
def build_cte(blocks, main):
    if not blocks:
        raise DbError("Добавьте хотя бы один блок CTE.")
    names = [n for n, _ in blocks]
    if len(set(names)) != len(names):
        raise DbError("Имена блоков CTE не должны повторяться.")
    parts = [sql.SQL("{} AS ({})").format(I(check_name(n, "имя блока CTE")), q) for n, q in blocks]
    return sql.SQL("WITH ") + sql.SQL(", ").join(parts) + sql.SQL(" ") + main


VIEW_KINDS = [("VIEW", "VIEW (обычное представление)"), ("MATERIALIZED VIEW", "MATERIALIZED VIEW (материализованное)")]


def _view_kind(kind):
    if kind not in ("VIEW", "MATERIALIZED VIEW"):
        raise DbError(f"Неизвестный вид представления: {kind}")
    return kind


# Создание представления
def build_create_view(name, kind, query, or_replace=False, with_data=True):
    n = I(SCHEMA, check_name(name, "имя представления"))
    if _view_kind(kind) == "VIEW":
        head = "CREATE OR REPLACE VIEW" if or_replace else "CREATE VIEW"
        return sql.SQL(head + " {} AS ").format(n) + query
    return (sql.SQL("CREATE MATERIALIZED VIEW {} AS ").format(n) + query
            + sql.SQL(" WITH DATA" if with_data else " WITH NO DATA"))


# Обновление материализованного представления
def build_refresh(name):
    return sql.SQL("REFRESH MATERIALIZED VIEW {}").format(I(SCHEMA, name))


# Переименование представления
def build_view_rename(name, kind, new_name):
    return sql.SQL("ALTER " + _view_kind(kind) + " {} RENAME TO {}").format(
        I(SCHEMA, name), I(check_name(new_name, "новое имя представления")))


# Удаление представления
def build_view_drop(name, kind, cascade=False):
    q = sql.SQL("DROP " + _view_kind(kind) + " {}").format(I(SCHEMA, name))
    return q + sql.SQL(" CASCADE") if cascade else q


# Данные представления
def build_view_data(name, limit=500):
    return sql.SQL("SELECT * FROM {} LIMIT {}").format(I(SCHEMA, name), L(limit))
