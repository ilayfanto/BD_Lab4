from datetime import date, datetime
from decimal import Decimal

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QRadioButton, QScrollArea, QSpinBox, QSplitter, QTableView, QTableWidget, QVBoxLayout, QWidget,
)

import builders as b
from db import DbError

TYPE_HINTS = ["text", "varchar(100)", "integer", "bigint", "smallint", "numeric(10,2)", "real", "boolean",
              "date", "timestamp", "timestamptz", "text[]", "integer[]", "attack_type", "model_family", "run_status"]

SEARCH_HINTS = {
    "LIKE": "LIKE — шаблон с учётом регистра: % — любые символы, _ — один символ. Пример: %Flow%",
    "ILIKE": "ILIKE — как LIKE, но без учёта регистра. Пример: %flow%",
    "NOT LIKE": "NOT LIKE — строки, которые НЕ подходят под шаблон. Пример: %-%",
    "~": "~ — POSIX-регулярка с учётом регистра. Пример: ^[A-Z]{2,4}-",
    "~*": "~* — POSIX-регулярка без учёта регистра. Пример: edge$",
    "!~": "!~ — НЕ соответствует регулярке (с учётом регистра). Пример: -",
    "!~*": "!~* — НЕ соответствует регулярке (без учёта регистра). Пример: ^rf",
    "SIMILAR TO": "SIMILAR TO — шаблон LIKE (%, _) плюс ( ) группы, | ИЛИ, [ ] диапазоны, {m,n} повторы. "
                  "Строка должна совпасть целиком. Пример: (RF|XGB)-%   или   [A-Z]{3}-%",
    "NOT SIMILAR TO": "NOT SIMILAR TO — строки, которые НЕ подходят под шаблон SIMILAR TO. Пример: (RF|XGB)-%",
}


# Окно ошибки
def show_error(parent, title, message):
    QMessageBox.critical(parent, title, message)


# Форматирование значения
def fmt(value):
    if isinstance(value, Decimal):
        return float(round(value, 4))
    if isinstance(value, (list, tuple)):
        return "{" + ", ".join(map(str, value)) + "}"
    if isinstance(value, (date, datetime)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    return value


# Таблица результата с сортировкой и фильтром
class ResultView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.quote = False
        self.model = QStandardItemModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setSortRole(Qt.UserRole)
        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.setAlternatingRowColors(True)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.filter_col = QComboBox()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Фильтр по результату…")
        self.filter_edit.textChanged.connect(self.apply_filter)
        self.filter_col.currentIndexChanged.connect(self.apply_filter)
        self.count = QLabel()
        top = QHBoxLayout()
        top.addWidget(QLabel("Фильтр:"))
        top.addWidget(self.filter_col)
        top.addWidget(self.filter_edit, 1)
        top.addWidget(self.count)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self.view)

    # Заполнение
    def show_rows(self, rows, cols):
        self.model.clear()
        self.model.setHorizontalHeaderLabels(cols)
        grey = QBrush(QColor(140, 140, 140))
        for row in rows:
            items = []
            for value in row:
                v = fmt(value)
                if v is None:
                    item = QStandardItem("NULL")
                    item.setForeground(grey)
                    item.setData("", Qt.UserRole)
                else:
                    shown = f"«{v}»" if self.quote and isinstance(v, str) else str(v)
                    item = QStandardItem(shown)
                    item.setData(v if isinstance(v, (int, float)) else str(v), Qt.UserRole)
                items.append(item)
            self.model.appendRow(items)
        self.filter_col.blockSignals(True)
        self.filter_col.clear()
        self.filter_col.addItem("Все столбцы", -1)
        for i, c in enumerate(cols):
            self.filter_col.addItem(c, i)
        self.filter_col.blockSignals(False)
        self.view.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        self.proxy.sort(-1)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.apply_filter()

    # Фильтр
    def apply_filter(self):
        self.proxy.setFilterKeyColumn(self.filter_col.currentData() if self.filter_col.count() else -1)
        self.proxy.setFilterFixedString(self.filter_edit.text())
        self.count.setText(f"строк: {self.proxy.rowCount()} из {self.model.rowCount()}")


# Поле с текстом SQL
def sql_box(height=70):
    box = QPlainTextEdit()
    box.setReadOnly(True)
    box.setMaximumHeight(height)
    box.setPlaceholderText("Здесь появится сгенерированный SQL")
    return box


# Список с галочками
def check_list(items, checked=True):
    w = QListWidget()
    for text in items:
        it = QListWidgetItem(text)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        w.addItem(it)
    return w


def checked_items(w):
    return [w.item(i).text() for i in range(w.count()) if w.item(i).checkState() == Qt.Checked]


# Редактор строк условий
class RowsEditor(QWidget):
    def __init__(self, headers, kinds, parent=None):
        super().__init__(parent)
        self.kinds = kinds
        self.options = [[] for _ in kinds]
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(90)
        add = QPushButton("+ добавить")
        rem = QPushButton("− удалить")
        add.clicked.connect(self.add_row)
        rem.clicked.connect(self.remove_row)
        btns = QHBoxLayout()
        btns.addWidget(add)
        btns.addWidget(rem)
        btns.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(btns)

    def set_options(self, idx, options):
        self.options[idx] = list(options)
        for r in range(self.table.rowCount()):
            combo = self.table.cellWidget(r, idx)
            current = combo.currentText()
            combo.clear()
            combo.addItems(self.options[idx])
            if current in self.options[idx] or (combo.isEditable() and current):
                combo.setCurrentText(current)

    def add_row(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, kind in enumerate(self.kinds):
            if kind in ("combo", "ecombo"):
                w = QComboBox()
                w.setEditable(kind == "ecombo")
                w.addItems(self.options[c])
            else:
                w = QLineEdit()
            self.table.setCellWidget(r, c, w)

    def remove_row(self):
        r = self.table.currentRow()
        self.table.removeRow(r if r >= 0 else self.table.rowCount() - 1)

    def clear(self):
        self.table.setRowCount(0)

    def values(self):
        out = []
        for r in range(self.table.rowCount()):
            row = []
            for c in range(len(self.kinds)):
                w = self.table.cellWidget(r, c)
                row.append(w.currentText().strip() if isinstance(w, QComboBox) else w.text())
            out.append(tuple(row))
        return out


# Окно ALTER TABLE
class AlterDialog(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Изменение структуры БД (ALTER TABLE)")
        self.setModal(True)
        self.resize(1150, 680)

        self.table = QComboBox()
        self.table.currentTextChanged.connect(self.refresh_structure)
        self.op = QComboBox()
        for key, title in b.ALTER_OPS:
            self.op.addItem(title, key)
        self.op.currentIndexChanged.connect(self.update_fields)

        self.column = QComboBox()
        self.name = QLineEdit()
        self.type = QComboBox()
        self.type.setEditable(True)
        self.type.addItems(TYPE_HINTS + [t for t in db.user_type_names() if t not in TYPE_HINTS])
        self.default = QLineEdit()
        self.not_null = QCheckBox("NOT NULL")
        self.using = QCheckBox("USING столбец::новый_тип (явное приведение)")
        self.cascade = QCheckBox("CASCADE (удалить зависимые объекты)")
        self.expr = QLineEdit()
        self.expr.setPlaceholderText("например: epochs <= 500 AND latency_ms >= 0")
        self.unique_cols = check_list([], checked=False)
        self.unique_cols.setMaximumHeight(110)
        self.ref_table = QComboBox()
        self.ref_table.currentTextChanged.connect(self.refresh_ref_columns)
        self.ref_column = QComboBox()
        self.on_delete = QComboBox()
        self.on_delete.addItems(b.FK_ACTIONS)
        self.on_update = QComboBox()
        self.on_update.addItems(b.FK_ACTIONS)
        self.constraint = QComboBox()

        self.form = QFormLayout()
        self.rows = {}
        for key, label, widget in [
            ("column", "Столбец:", self.column), ("name", "Новое имя:", self.name), ("type", "Тип данных:", self.type),
            ("default", "Значение по умолчанию:", self.default), ("not_null", "", self.not_null),
            ("using", "", self.using), ("expr", "Условие CHECK:", self.expr), ("unique", "Столбцы UNIQUE:", self.unique_cols),
            ("ref_table", "Таблица-родитель:", self.ref_table), ("ref_column", "Столбец-родитель:", self.ref_column),
            ("on_delete", "ON DELETE:", self.on_delete), ("on_update", "ON UPDATE:", self.on_update),
            ("constraint", "Ограничение:", self.constraint), ("cascade", "", self.cascade),
        ]:
            self.form.addRow(label, widget)
            self.rows[key] = widget

        for w in (self.name, self.default, self.expr):
            w.textChanged.connect(self.update_preview)
        for w in (self.column, self.type, self.ref_table, self.ref_column, self.on_delete, self.on_update, self.constraint):
            w.currentTextChanged.connect(self.update_preview)
        for w in (self.not_null, self.using, self.cascade):
            w.toggled.connect(self.update_preview)
        self.unique_cols.itemChanged.connect(self.update_preview)

        self.preview = sql_box(80)
        run = QPushButton("Выполнить ALTER TABLE")
        run.setMinimumHeight(34)
        run.clicked.connect(self.execute)

        left = QWidget()
        lv = QVBoxLayout(left)
        top = QFormLayout()
        top.addRow("Таблица:", self.table)
        top.addRow("Операция:", self.op)
        lv.addLayout(top)
        params = QGroupBox("Параметры")
        params.setLayout(self.form)
        lv.addWidget(params)
        lv.addWidget(QLabel("SQL:"))
        lv.addWidget(self.preview)
        lv.addWidget(run)
        lv.addStretch()

        self.cols_view = ResultView()
        self.cons_view = ResultView()
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(QLabel("Столбцы таблицы:"))
        rv.addWidget(self.cols_view, 3)
        rv.addWidget(QLabel("Ограничения таблицы:"))
        rv.addWidget(self.cons_view, 2)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([480, 670])
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(split)
        layout.addWidget(close, alignment=Qt.AlignRight)

        self.reload_tables()
        self.update_fields()

    # Обновление списка таблиц
    def reload_tables(self, select=None):
        tables = self.db.tables()
        for combo in (self.table, self.ref_table):
            current = select if combo is self.table and select else combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(tables)
            if current in tables:
                combo.setCurrentText(current)
            combo.blockSignals(False)
        self.refresh_structure()
        self.refresh_ref_columns()

    # Структура выбранной таблицы
    def refresh_structure(self):
        table = self.table.currentText()
        if not table:
            return
        try:
            cols = self.db.columns(table)
            cons = self.db.constraints(table)
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        self.cols_view.show_rows([(c[0], c[1], "да" if c[2] else "нет", c[3]) for c in cols],
                                 ["Столбец", "Тип", "NULL допустим", "По умолчанию"])
        self.cons_view.show_rows(cons, ["Имя", "Вид", "Определение"])
        names = [c[0] for c in cols]
        self.column.blockSignals(True)
        self.column.clear()
        self.column.addItems(names)
        self.column.blockSignals(False)
        self.unique_cols.clear()
        for n in names:
            it = QListWidgetItem(n)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            self.unique_cols.addItem(it)
        self.constraint.blockSignals(True)
        self.constraint.clear()
        self.constraint.addItems([c[0] for c in cons])
        self.constraint.blockSignals(False)
        self.update_preview()

    def refresh_ref_columns(self):
        table = self.ref_table.currentText()
        self.ref_column.clear()
        if table:
            try:
                self.ref_column.addItems(self.db.column_names(table))
            except DbError:
                pass

    # Видимость полей под операцию
    def update_fields(self):
        op = self.op.currentData()
        visible = {
            "add_column": {"name", "type", "default", "not_null"},
            "drop_column": {"column", "cascade"},
            "rename_column": {"column", "name"},
            "rename_table": {"name"},
            "alter_type": {"column", "type", "using"},
            "set_not_null": {"column"},
            "drop_not_null": {"column"},
            "set_default": {"column", "default"},
            "drop_default": {"column"},
            "add_check": {"name", "expr"},
            "add_unique": {"name", "unique"},
            "add_fk": {"name", "column", "ref_table", "ref_column", "on_delete", "on_update"},
            "drop_constraint": {"constraint", "cascade"},
        }[op]
        for key, widget in self.rows.items():
            self.form.setRowVisible(widget, key in visible)
        self.form.labelForField(self.name).setText(
            "Имя ограничения:" if op in ("add_check", "add_unique", "add_fk") else
            "Имя столбца:" if op == "add_column" else "Новое имя:")
        self.form.labelForField(self.type).setText("Новый тип:" if op == "alter_type" else "Тип данных:")
        self.update_preview()

    def params(self):
        return {
            "column": self.column.currentText(), "name": self.name.text().strip(), "type": self.type.currentText(),
            "default": self.default.text(), "not_null": self.not_null.isChecked(), "using": self.using.isChecked(),
            "cascade": self.cascade.isChecked(), "expr": self.expr.text().strip(),
            "columns": checked_items(self.unique_cols), "ref_table": self.ref_table.currentText(),
            "ref_column": self.ref_column.currentText(), "on_delete": self.on_delete.currentText(),
            "on_update": self.on_update.currentText(), "constraint": self.constraint.currentText(),
        }

    def statement(self):
        return b.build_alter(self.op.currentData(), self.table.currentText(), self.params())

    # Предпросмотр SQL
    def update_preview(self):
        if not self.table.currentText():
            return
        try:
            self.preview.setPlainText(self.db.preview(self.statement()))
        except DbError as e:
            self.preview.setPlainText(f"-- {e}")

    # Выполнение
    def execute(self):
        try:
            text = self.db.alter(self.statement())
        except DbError as e:
            show_error(self, "Ошибка ALTER TABLE — выполнен ROLLBACK", str(e))
            return
        new_table = self.name.text().strip() if self.op.currentData() == "rename_table" else None
        self.reload_tables(select=new_table)
        if self.parent() is not None and hasattr(self.parent(), "note"):
            self.parent().note(f"ALTER: {text}")
        QMessageBox.information(self, "Готово", f"Структура изменена:\n{text}")


# Конструктор SELECT
class SelectBuilderTab(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.table = QComboBox()
        self.table.addItems(db.selectables())
        self.table.currentTextChanged.connect(self.load_columns)
        self.columns = check_list([])
        self.columns.setMinimumHeight(170)
        self.aggs = RowsEditor(["Функция", "Столбец", "Псевдоним"], ["combo", "combo", "edit"])
        self.aggs.set_options(0, b.AGG_FUNCS)
        self.where = RowsEditor(["Столбец", "Оператор", "Значение"], ["combo", "combo", "edit"])
        self.where.set_options(1, b.WHERE_OPS)
        self.where_join = QComboBox()
        self.where_join.addItems(["AND", "OR"])
        self.group = check_list([], checked=False)
        self.group.setMinimumHeight(150)
        self.having = RowsEditor(["Функция", "Столбец", "Оператор", "Значение"], ["combo", "combo", "combo", "edit"])
        self.having.set_options(0, b.AGG_FUNCS)
        self.having.set_options(2, b.COMPARE_OPS)
        self.order = RowsEditor(["Поле или псевдоним", "Направление"], ["ecombo", "combo"])
        self.order.set_options(1, b.DIRECTIONS)
        self.limit = QSpinBox()
        self.limit.setRange(0, 100000)
        self.limit.setSpecialValueText("без ограничения")

        run = QPushButton("Выполнить SELECT")
        run.setMinimumHeight(32)
        run.clicked.connect(self.execute)
        reset = QPushButton("Сбросить")
        reset.clicked.connect(self.reset)

        cfg = QWidget()
        form = QVBoxLayout(cfg)
        self.cfg_layout = form
        row = QFormLayout()
        row.addRow("FROM (таблица):", self.table)
        form.addLayout(row)
        for title, widget in [("SELECT — столбцы", self.columns), ("Агрегатные функции (COUNT, SUM, AVG, MIN, MAX)", self.aggs)]:
            form.addWidget(self._group(title, widget))
        wbox = QGroupBox("WHERE — фильтр строк")
        wl = QVBoxLayout(wbox)
        jl = QHBoxLayout()
        jl.addWidget(QLabel("Объединять условия через:"))
        jl.addWidget(self.where_join)
        jl.addStretch()
        wl.addLayout(jl)
        wl.addWidget(self.where)
        form.addWidget(wbox)
        self.group_box = self._group("GROUP BY — группировка", self.group)
        form.addWidget(self.group_box)
        form.addWidget(self._group("HAVING — фильтр групп", self.having))
        form.addWidget(self._group("ORDER BY — сортировка", self.order))
        lrow = QFormLayout()
        lrow.addRow("LIMIT:", self.limit)
        form.addLayout(lrow)
        btns = QHBoxLayout()
        btns.addWidget(run)
        btns.addWidget(reset)
        form.addLayout(btns)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(cfg)
        scroll.setMinimumWidth(440)

        self.preview = sql_box()
        self.result = ResultView()
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(QLabel("Сгенерированный SQL:"))
        rv.addWidget(self.preview)
        rv.addWidget(self.result)

        split = QSplitter()
        split.addWidget(scroll)
        split.addWidget(right)
        split.setSizes([460, 800])
        layout = QVBoxLayout(self)
        layout.addWidget(split)
        self.load_columns()

    def _group(self, title, widget):
        box = QGroupBox(title)
        QVBoxLayout(box).addWidget(widget)
        return box

    # Столбцы выбранной таблицы
    def load_columns(self):
        table = self.table.currentText()
        if not table:
            return
        cols = self.db.column_names(table)
        self.columns.clear()
        self.group.clear()
        for c in cols:
            for w, state in ((self.columns, Qt.Checked), (self.group, Qt.Unchecked)):
                it = QListWidgetItem(c)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(state)
                w.addItem(it)
        for editor in (self.aggs, self.having):
            editor.clear()
            editor.set_options(1, ["*"] + cols)
        self.where.clear()
        self.where.set_options(0, cols)
        self.order.clear()
        self.order.set_options(0, cols)

    def reset(self):
        self.load_columns()
        self.limit.setValue(0)
        self.preview.clear()

    def computed(self):
        return []

    def extra_args(self):
        return {}

    # Сборка запроса
    def build_query(self):
        where = [w for w in self.where.values() if w[0]]
        return b.build_select(
            self.table.currentText(), checked_items(self.columns), self.aggs.values(), where,
            self.where_join.currentText(), checked_items(self.group), self.having.values(),
            [o for o in self.order.values() if o[0]], self.limit.value(), self.computed(), **self.extra_args())

    # Выполнение
    def execute(self):
        try:
            rows, cols, text = self.db.run_query(self.build_query())
        except DbError as e:
            show_error(self, "Ошибка SELECT", str(e))
            return
        self.preview.setPlainText(text)
        self.result.show_rows(rows, cols)


# Поиск по тексту
class SearchTab(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.table = QComboBox()
        self.table.addItems(db.selectables())
        self.table.currentTextChanged.connect(self.load_columns)
        self.column = QComboBox()
        self.mode = QComboBox()
        self.mode.addItems(b.TEXT_OPS)
        self.mode.currentTextChanged.connect(lambda m: self.hint.setText(SEARCH_HINTS[m]))
        self.pattern = QLineEdit()
        self.pattern.returnPressed.connect(self.execute)
        self.hint = QLabel(SEARCH_HINTS["LIKE"])
        self.hint.setWordWrap(True)
        run = QPushButton("Найти")
        run.clicked.connect(self.execute)

        form = QFormLayout()
        form.addRow("Таблица:", self.table)
        form.addRow("Столбец:", self.column)
        form.addRow("Тип поиска:", self.mode)
        pr = QHBoxLayout()
        pr.addWidget(self.pattern, 1)
        pr.addWidget(run)
        form.addRow("Шаблон:", pr)
        form.addRow("", self.hint)
        self.test_text = QLineEdit("RF-NetFlow")
        self.test_text.returnPressed.connect(self.test_match)
        test = QPushButton("Проверить строку")
        test.clicked.connect(self.test_match)
        self.test_result = QLabel()
        tr = QHBoxLayout()
        tr.addWidget(self.test_text, 1)
        tr.addWidget(test)
        tr.addWidget(self.test_result)
        form.addRow("Своя строка:", tr)
        self.preview = sql_box(50)
        self.result = ResultView()
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.preview)
        layout.addWidget(self.result)
        self.load_columns()

    def load_columns(self):
        if self.table.currentText():
            self.column.clear()
            self.column.addItems(self.db.column_names(self.table.currentText()))

    # Проверка своей строки на шаблон
    def test_match(self):
        try:
            rows, _, text = self.db.run_query(
                b.build_match_test(self.test_text.text(), self.mode.currentText(), self.pattern.text()))
        except DbError as e:
            show_error(self, "Ошибка проверки", str(e))
            return
        ok = rows[0][0]
        self.preview.setPlainText(text)
        self.test_result.setText("✔ TRUE — подходит" if ok else "✖ FALSE — не подходит")

    def execute(self):
        table = self.table.currentText()
        try:
            q = b.build_select(table, self.db.column_names(table),
                               where=[(self.column.currentText(), self.mode.currentText(), self.pattern.text())])
            rows, cols, text = self.db.run_query(q)
        except DbError as e:
            show_error(self, "Ошибка поиска", str(e))
            return
        self.preview.setPlainText(text)
        self.result.show_rows(rows, cols)


# Мастер JOIN
class JoinWizardTab(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.tables = db.selectables()
        self.cols = {t: db.column_names(t) for t in self.tables}
        self.fks = db.foreign_keys()
        self.base = QComboBox()
        self.base.addItems(self.tables)
        self.base.currentTextChanged.connect(self.refresh_all)
        self.steps = QTableWidget(0, 4)
        self.steps.setHorizontalHeaderLabels(["Тип соединения", "Таблица", "Левое поле (ON)", "Правое поле (ON)"])
        self.steps.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.steps.verticalHeader().setVisible(False)
        self.steps.setMaximumHeight(150)
        add = QPushButton("+ присоединить таблицу")
        add.clicked.connect(self.add_step)
        rem = QPushButton("− убрать последнюю")
        rem.clicked.connect(lambda: self.steps.removeRow(self.steps.rowCount() - 1))
        run = QPushButton("Выполнить JOIN")
        run.setMinimumHeight(32)
        run.clicked.connect(self.execute)

        top = QHBoxLayout()
        top.addWidget(QLabel("Основная таблица (t1):"))
        top.addWidget(self.base, 1)
        top.addWidget(add)
        top.addWidget(rem)
        top.addWidget(run)
        self.preview = sql_box(60)
        self.result = ResultView()
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.steps)
        layout.addWidget(QLabel("Подсказка: поля связи подставляются по внешним ключам; NULL — строки без пары. "
                                "Результат можно сортировать щелчком по заголовку и фильтровать."))
        layout.addWidget(self.preview)
        layout.addWidget(self.result)
        if len(self.tables) > 1:
            self.add_step()

    def add_step(self):
        r = self.steps.rowCount()
        self.steps.insertRow(r)
        jt = QComboBox()
        jt.addItems(b.JOIN_TYPES)
        tb = QComboBox()
        tb.addItems(self.tables)
        prev = [self.base.currentText()] + [self.steps.cellWidget(i, 1).currentText() for i in range(r)]
        for t in self.tables:
            if t not in prev and self._fk_between(prev, t):
                tb.setCurrentText(t)
                break
        tb.currentTextChanged.connect(lambda _=None, row=r: self.refresh_row(row))
        jt.currentTextChanged.connect(lambda _=None, row=r: self.refresh_row(row))
        for c, w in enumerate((jt, tb, QComboBox(), QComboBox())):
            self.steps.setCellWidget(r, c, w)
        self.refresh_row(r)

    def _fk_between(self, prev, table):
        return any((ct == table and rt in prev) or (rt == table and ct in prev) for ct, _, rt, _ in self.fks)

    def aliases(self, upto):
        out = [("t1", self.base.currentText())]
        for i in range(upto):
            out.append((f"t{i + 2}", self.steps.cellWidget(i, 1).currentText()))
        return out

    def refresh_all(self):
        for r in range(self.steps.rowCount()):
            self.refresh_row(r)

    # Поля связи для шага
    def refresh_row(self, r):
        if r >= self.steps.rowCount():
            return
        jt, tb, left, right = (self.steps.cellWidget(r, c) for c in range(4))
        table, alias = tb.currentText(), f"t{r + 2}"
        left.clear()
        right.clear()
        cross = jt.currentText() == "CROSS JOIN"
        left.setEnabled(not cross)
        right.setEnabled(not cross)
        prev = self.aliases(r)
        for a, t in prev:
            for c in self.cols.get(t, []):
                left.addItem(f"{a}.{c}  ({t})", (a, c))
        for c in self.cols.get(table, []):
            right.addItem(f"{alias}.{c}", c)
        for a, t in reversed(prev):
            for ct, cc, rt, rc in self.fks:
                if ct == table and rt == t:
                    self._select(left, (a, rc))
                    self._select(right, cc)
                    return
                if ct == t and rt == table:
                    self._select(left, (a, cc))
                    self._select(right, rc)
                    return

    @staticmethod
    def _select(combo, data):
        i = combo.findData(data)
        if i >= 0:
            combo.setCurrentIndex(i)

    # Сборка запроса
    def build_query(self):
        steps = []
        for r in range(self.steps.rowCount()):
            jt, tb, left, right = (self.steps.cellWidget(r, c) for c in range(4))
            steps.append((jt.currentText(), tb.currentText(), left.currentData(), right.currentData()))
        return b.build_join(self.base.currentText(), steps, self.cols)

    def execute(self):
        try:
            rows, cols, text = self.db.run_query(self.build_query())
        except DbError as e:
            show_error(self, "Ошибка JOIN", str(e))
            return
        self.preview.setPlainText(text)
        self.result.show_rows(rows, cols)


# Окно строковых функций
class StringsDialog(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Функции работы со строками")
        self.setModal(True)
        self.resize(1150, 650)

        self.src_col = QRadioButton("Столбец таблицы")
        self.src_lit = QRadioButton("Своя строка")
        self.src_col.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.src_col)
        group.addButton(self.src_lit)
        self.table = QComboBox()
        self.table.addItems(db.selectables())
        self.table.currentTextChanged.connect(self.load_columns)
        self.column = QComboBox()
        self.column2 = QComboBox()
        self.literal = QLineEdit("   DDoS Detection Model   ")
        self.func = QComboBox()
        for key, title, _ in b.STRING_FUNCS:
            self.func.addItem(title, key)
        self.func.currentIndexChanged.connect(self.update_params)
        self.p1 = QLineEdit()
        self.p2 = QLineEdit()
        self.quote = QCheckBox("Показывать границы строк «…» (видно пробелы)")
        self.quote.setChecked(True)

        run = QPushButton("Применить функцию")
        run.clicked.connect(self.execute)
        all_btn = QPushButton("Все функции сразу")
        all_btn.clicked.connect(self.execute_all)

        self.form = QFormLayout()
        src = QHBoxLayout()
        src.addWidget(self.src_col)
        src.addWidget(self.src_lit)
        src.addStretch()
        self.form.addRow("Источник:", src)
        self.form.addRow("Таблица:", self.table)
        self.form.addRow("Столбец:", self.column)
        self.form.addRow("Строка:", self.literal)
        self.form.addRow("Функция:", self.func)
        self.form.addRow("Параметр 1:", self.p1)
        self.form.addRow("Параметр 2:", self.p2)
        self.form.addRow("2-й столбец:", self.column2)
        self.form.addRow("", self.quote)
        btns = QHBoxLayout()
        btns.addWidget(run)
        btns.addWidget(all_btn)
        btns.addStretch()
        self.form.addRow(btns)
        self.src_col.toggled.connect(self.update_source)

        self.preview = sql_box(70)
        self.result = ResultView()
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.preview)
        layout.addWidget(self.result)
        layout.addWidget(close, alignment=Qt.AlignRight)
        self.load_columns()
        self.update_params()
        self.update_source()

    def load_columns(self):
        table = self.table.currentText()
        if not table:
            return
        cols = self.db.column_names(table)
        self.column.clear()
        self.column.addItems(cols)
        self.column2.clear()
        self.column2.addItem("— нет —", None)
        for c in cols:
            self.column2.addItem(c, c)
        if "name" in cols:
            self.column.setCurrentText("name")

    def update_source(self):
        col = self.src_col.isChecked()
        for w in (self.table, self.column):
            self.form.setRowVisible(w, col)
        self.form.setRowVisible(self.literal, not col)
        self.update_params()

    # Подписи параметров под функцию
    def update_params(self):
        labels = dict((k, p) for k, _, p in b.STRING_FUNCS)[self.func.currentData()]
        for i, edit in enumerate((self.p1, self.p2)):
            show = i < len(labels)
            self.form.setRowVisible(edit, show)
            if show:
                self.form.labelForField(edit).setText(labels[i] + ":")
        concat = self.func.currentData() in ("CONCAT", "PIPES")
        self.form.setRowVisible(self.column2, concat and self.src_col.isChecked())
        defaults = {"TRIM": ("", ""), "SUBSTRING": ("1", "5"), "SUBSTRING_RE": ("-(.+)$", ""), "POSITION": ("-", ""),
                    "REPLACE": ("-", " / "), "LPAD": ("20", "*"), "RPAD": ("20", "."), "CONCAT": (" | ", "v1"),
                    "PIPES": (" — ", "DDoS")}
        p1, p2 = defaults.get(self.func.currentData(), ("", ""))
        self.p1.setText(p1)
        self.p2.setText(p2)

    def source(self):
        if self.src_col.isChecked():
            return {"table": self.table.currentText(), "column": self.column.currentText()}
        return {"literal": self.literal.text()}

    def _show(self, q):
        try:
            rows, cols, text = self.db.run_query(q)
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        self.preview.setPlainText(text)
        self.result.quote = self.quote.isChecked()
        self.result.show_rows(rows, cols)

    def execute(self):
        try:
            q = b.build_string(self.func.currentData(), p1=self.p1.text(), p2=self.p2.text(),
                               column2=self.column2.currentData() if self.src_col.isChecked() else None,
                               **self.source())
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        self._show(q)

    def execute_all(self):
        self._show(b.build_all_strings(**self.source()))
