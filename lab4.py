from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLayout, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget,
    QVBoxLayout, QWidget,
)

import builders as b
from db import DbError
from lab2 import JoinWizardTab, ResultView, RowsEditor, check_list, checked_items, show_error, sql_box
from lab3 import SelectBuilderTab3

NO_JOIN = "без соединения"


def set_items(widget, items, checked=False):
    widget.clear()
    for text in items:
        it = QListWidgetItem(text)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        widget.addItem(it)


def group(title, *widgets):
    box = QGroupBox(title)
    lay = QVBoxLayout(box)
    for w in widgets:
        if isinstance(w, QLayout):
            lay.addLayout(w)
        else:
            lay.addWidget(w)
    return box


# Конструктор SELECT с ROLLUP / CUBE / GROUPING SETS
class SelectBuilderTab4(SelectBuilderTab3):
    def __init__(self, db, parent=None):
        super().__init__(db, parent)
        self.sets = []
        self.mode = QComboBox()
        for key, title in b.GROUPING_MODES:
            self.mode.addItem(title, key)
        self.mode.currentIndexChanged.connect(self.update_mode)
        up = QPushButton("▲ выше")
        down = QPushButton("▼ ниже")
        up.clicked.connect(lambda: self.move_group(-1))
        down.clicked.connect(lambda: self.move_group(1))
        order_row = QHBoxLayout()
        order_row.addWidget(QLabel("Порядок столбцов GROUP BY (важен для ROLLUP):"))
        order_row.addWidget(up)
        order_row.addWidget(down)
        order_row.addStretch()
        self.sets_list = QListWidget()
        self.sets_list.setMaximumHeight(100)
        self.add_set = QPushButton("+ набор из отмеченных в GROUP BY")
        self.add_set.clicked.connect(self.add_grouping_set)
        self.add_total = QPushButton("+ общий итог ()")
        self.add_total.clicked.connect(lambda: self.append_set([]))
        self.del_set = QPushButton("− удалить набор")
        self.del_set.clicked.connect(self.remove_set)
        sets_row = QHBoxLayout()
        for w in (self.add_set, self.add_total, self.del_set):
            sets_row.addWidget(w)
        self.label_totals = QCheckBox("Подписывать итоговые строки «ИТОГО»")
        self.label_totals.setChecked(True)
        self.show_grouping = QCheckBox("Показать столбец GROUPING() — уровень детализации")
        self.show_grouping.setChecked(True)
        demo = QPushButton("Пример отчёта: запуски по статусу и GPU")
        demo.clicked.connect(self.demo)
        form = QFormLayout()
        form.addRow("Режим:", self.mode)
        box = group("Расширенная группировка: ROLLUP / CUBE / GROUPING SETS", form, order_row,
                    QLabel("Наборы GROUPING SETS:"), self.sets_list, sets_row, self.label_totals,
                    self.show_grouping, demo)
        self.cfg_layout.insertWidget(self.cfg_layout.indexOf(self.group_box) + 1, box)
        self.update_mode()

    def update_mode(self):
        sets = self.mode.currentData() == "sets"
        for w in (self.sets_list, self.add_set, self.add_total, self.del_set):
            w.setEnabled(sets)
        plain = self.mode.currentData() == "plain"
        self.label_totals.setEnabled(not plain)
        self.show_grouping.setEnabled(not plain)

    def move_group(self, step):
        r = self.group.currentRow()
        if r < 0 or not 0 <= r + step < self.group.count():
            return
        item = self.group.takeItem(r)
        self.group.insertItem(r + step, item)
        self.group.setCurrentRow(r + step)

    def append_set(self, cols):
        self.sets.append(list(cols))
        self.sets_list.addItem("(" + ", ".join(cols) + ")")

    def add_grouping_set(self):
        cols = checked_items(self.group)
        if not cols:
            show_error(self, "GROUPING SETS", "Отметьте столбцы в блоке GROUP BY, затем добавьте набор.")
            return
        self.append_set(cols)

    def remove_set(self):
        r = self.sets_list.currentRow()
        r = r if r >= 0 else self.sets_list.count() - 1
        if r >= 0:
            self.sets_list.takeItem(r)
            self.sets.pop(r)

    def load_columns(self):
        super().load_columns()
        if hasattr(self, "sets"):
            self.sets.clear()
            self.sets_list.clear()

    def extra_args(self):
        return dict(grouping=self.mode.currentData(), grouping_sets=self.sets,
                    label_totals=self.label_totals.isChecked(), show_grouping=self.show_grouping.isChecked())

    # Выполнение с выделением итоговых строк
    def execute(self):
        super().execute()
        model = self.result.model
        headers = [model.horizontalHeaderItem(i).text() for i in range(model.columnCount())]
        if "grouping_level" not in headers:
            return
        col = headers.index("grouping_level")
        bold = QFont()
        bold.setBold(True)
        for r in range(model.rowCount()):
            if model.item(r, col).text() not in ("0", "NULL"):
                for c in range(model.columnCount()):
                    model.item(r, c).setFont(bold)

    # Пример отчёта
    def demo(self):
        self.table.setCurrentText("runs")
        for w in (self.columns, self.group):
            for i in range(w.count()):
                w.item(i).setCheckState(Qt.Checked if w.item(i).text() in ("status", "gpu_used") else Qt.Unchecked)
        self.aggs.clear()
        for func, col, alias in (("COUNT", "*", "runs"), ("AVG", "f1_score", "avg_f1"), ("MAX", "f1_score", "best_f1")):
            self.aggs.add_row()
            r = self.aggs.table.rowCount() - 1
            self.aggs.table.cellWidget(r, 0).setCurrentText(func)
            self.aggs.table.cellWidget(r, 1).setCurrentText(col)
            self.aggs.table.cellWidget(r, 2).setText(alias)
        self.mode.setCurrentIndex(self.mode.findData("rollup"))
        self.execute()


# Редактор одного блока запроса
class QueryBlockEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.columns = check_list([])
        self.columns.setMinimumHeight(120)
        self.aggs = RowsEditor(["Функция", "Столбец", "Псевдоним"], ["combo", "combo", "edit"])
        self.aggs.set_options(0, b.AGG_FUNCS)
        self.where = RowsEditor(["Столбец", "Оператор", "Значение"], ["combo", "combo", "edit"])
        self.where.set_options(1, b.WHERE_OPS)
        self.group = check_list([], checked=False)
        self.group.setMinimumHeight(100)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(group("SELECT — столбцы", self.columns))
        lay.addWidget(group("Агрегаты", self.aggs))
        lay.addWidget(group("WHERE", self.where))
        lay.addWidget(group("GROUP BY", self.group))

    def set_columns(self, cols):
        set_items(self.columns, cols, checked=True)
        set_items(self.group, cols)
        self.aggs.clear()
        self.aggs.set_options(1, ["*"] + cols)
        self.where.clear()
        self.where.set_options(0, cols)

    def build(self, table, cte_names):
        return b.build_select(table, checked_items(self.columns), self.aggs.values(),
                              [w for w in self.where.values() if w[0]], "AND", checked_items(self.group),
                              cte_names=cte_names)

    def output_columns(self):
        out = checked_items(self.columns)
        for func, col, alias in self.aggs.values():
            out.append(alias or f"{func.lower()}_{'all' if col == '*' else col}")
        return out


# Конструктор CTE
class CteBuilderTab(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.blocks = []

        self.block_name = QLineEdit("run_stats")
        self.block_source = QComboBox()
        self.block_source.currentTextChanged.connect(self.block_source_changed)
        self.block = QueryBlockEditor()
        add_block = QPushButton("Добавить блок в WITH")
        add_block.clicked.connect(self.add_block)
        bf = QFormLayout()
        bf.addRow("Имя блока:", self.block_name)
        bf.addRow("FROM:", self.block_source)
        block_box = group("1. Блок CTE: имя AS (SELECT …)", bf, self.block, add_block)

        self.blocks_list = QListWidget()
        self.blocks_list.setMinimumHeight(90)
        rem = QPushButton("− убрать последний блок")
        rem.clicked.connect(self.remove_block)
        clr = QPushButton("Очистить")
        clr.clicked.connect(self.clear_blocks)
        br = QHBoxLayout()
        br.addWidget(rem)
        br.addWidget(clr)
        br.addStretch()
        list_box = group("2. Блоки WITH (каждый следующий может читать предыдущие)", self.blocks_list, br)

        self.main_source = QComboBox()
        self.main_source.currentTextChanged.connect(self.main_changed)
        self.join_type = QComboBox()
        self.join_type.addItems([NO_JOIN] + b.JOIN_TYPES)
        self.join_type.currentTextChanged.connect(self.main_changed)
        self.join_source = QComboBox()
        self.join_source.currentTextChanged.connect(self.main_changed)
        self.left_col = QComboBox()
        self.right_col = QComboBox()
        self.main_cols = check_list([])
        self.main_cols.setMinimumHeight(120)
        self.main_where = RowsEditor(["Столбец", "Оператор", "Значение"], ["combo", "combo", "edit"])
        self.main_where.set_options(1, b.WHERE_OPS)
        self.main_order = RowsEditor(["Столбец", "Направление"], ["combo", "combo"])
        self.main_order.set_options(1, b.DIRECTIONS)
        self.limit = QSpinBox()
        self.limit.setRange(0, 100000)
        self.limit.setSpecialValueText("без ограничения")
        mf = QFormLayout()
        mf.addRow("FROM (a):", self.main_source)
        mf.addRow("Соединение:", self.join_type)
        mf.addRow("С источником (b):", self.join_source)
        on = QHBoxLayout()
        on.addWidget(QLabel("a."))
        on.addWidget(self.left_col, 1)
        on.addWidget(QLabel("= b."))
        on.addWidget(self.right_col, 1)
        mf.addRow("ON:", on)
        mf.addRow("LIMIT:", self.limit)
        main_box = group("3. Итоговый SELECT", mf, QLabel("Столбцы:"), self.main_cols, QLabel("WHERE:"),
                         self.main_where, QLabel("ORDER BY:"), self.main_order)

        run = QPushButton("Выполнить WITH-запрос")
        run.setMinimumHeight(32)
        run.clicked.connect(self.execute)
        demo = QPushButton("Пример: лучшие эксперименты")
        demo.clicked.connect(self.demo)
        rr = QHBoxLayout()
        rr.addWidget(run)
        rr.addWidget(demo)

        left = QWidget()
        lv = QVBoxLayout(left)
        for w in (block_box, list_box, main_box):
            lv.addWidget(w)
        lv.addLayout(rr)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        scroll.setMinimumWidth(520)

        self.preview = sql_box(110)
        self.result = ResultView()
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(QLabel("Сгенерированный SQL:"))
        rv.addWidget(self.preview)
        rv.addWidget(self.result)
        split = QSplitter()
        split.addWidget(scroll)
        split.addWidget(right)
        split.setSizes([560, 720])
        QVBoxLayout(self).addWidget(split)
        self.refresh_sources()

    def cte_names(self):
        return [blk["name"] for blk in self.blocks]

    def columns_of(self, src):
        for blk in self.blocks:
            if blk["name"] == src:
                return blk["columns"]
        return self.db.column_names(src) if src else []

    # Обновление списков источников
    def refresh_sources(self):
        sources = self.cte_names() + self.db.selectables()
        for combo in (self.block_source, self.main_source, self.join_source):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(sources)
            if current in sources:
                combo.setCurrentText(current)
            elif combo is not self.block_source and self.blocks:
                combo.setCurrentText(self.blocks[-1]["name"])
            combo.blockSignals(False)
        self.block_source_changed()
        self.main_changed()

    def block_source_changed(self):
        self.block.set_columns(self.columns_of(self.block_source.currentText()))

    def main_changed(self):
        joined = self.join_type.currentText() != NO_JOIN
        cross = self.join_type.currentText() == "CROSS JOIN"
        self.join_source.setEnabled(joined)
        self.left_col.setEnabled(joined and not cross)
        self.right_col.setEnabled(joined and not cross)
        a_cols = self.columns_of(self.main_source.currentText())
        b_cols = self.columns_of(self.join_source.currentText()) if joined else []
        self.left_col.clear()
        self.left_col.addItems(a_cols)
        self.right_col.clear()
        self.right_col.addItems(b_cols)
        common = [c for c in a_cols if c in b_cols]
        if common:
            self.left_col.setCurrentText(common[0])
            self.right_col.setCurrentText(common[0])
        qualified = [f"a.{c}" for c in a_cols] + [f"b.{c}" for c in b_cols]
        set_items(self.main_cols, qualified, checked=True)
        self.main_where.clear()
        self.main_where.set_options(0, qualified)
        self.main_order.clear()
        self.main_order.set_options(0, qualified)

    def add_block(self):
        name = self.block_name.text().strip()
        try:
            b.check_name(name, "имя блока CTE")
            if name in self.cte_names():
                raise DbError(f"Блок «{name}» уже есть.")
            query = self.block.build(self.block_source.currentText(), self.cte_names())
            text = self.db.preview(query)
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        self.blocks.append({"name": name, "query": query, "columns": self.block.output_columns()})
        self.blocks_list.addItem(f"{name} AS ({text})")
        self.block_name.setText(f"step{len(self.blocks) + 1}")
        self.refresh_sources()

    def remove_block(self):
        if self.blocks:
            self.blocks.pop()
            self.blocks_list.takeItem(self.blocks_list.count() - 1)
            self.refresh_sources()

    def clear_blocks(self):
        self.blocks.clear()
        self.blocks_list.clear()
        self.refresh_sources()

    @staticmethod
    def split(qualified):
        alias, col = qualified.split(".", 1)
        return alias, col

    # Сборка запроса
    def build_query(self):
        join = None
        if self.join_type.currentText() != NO_JOIN:
            join = (self.join_type.currentText(), self.join_source.currentText(),
                    self.left_col.currentText(), self.right_col.currentText())
        columns = [self.split(c) for c in checked_items(self.main_cols)]
        where = [self.split(c) + (op, v) for c, op, v in self.main_where.values() if c]
        order = [self.split(c) + (d,) for c, d in self.main_order.values() if c]
        main = b.build_cte_main(self.main_source.currentText(), columns, join, where, order, self.limit.value(),
                                self.cte_names())
        return b.build_cte([(blk["name"], blk["query"]) for blk in self.blocks], main)

    def execute(self):
        try:
            rows, cols, text = self.db.run_query(self.build_query())
        except DbError as e:
            show_error(self, "Ошибка WITH-запроса", str(e))
            return
        self.preview.setPlainText(text)
        self.result.show_rows(rows, cols)

    # Пример
    def demo(self):
        self.clear_blocks()
        self.block_name.setText("run_stats")
        self.block_source.setCurrentText("runs")
        cols = self.block.columns
        for i in range(cols.count()):
            cols.item(i).setCheckState(Qt.Checked if cols.item(i).text() == "experiment_id" else Qt.Unchecked)
        for i in range(self.block.group.count()):
            if self.block.group.item(i).text() == "experiment_id":
                self.block.group.item(i).setCheckState(Qt.Checked)
        for func, col, alias in (("COUNT", "*", "runs"), ("AVG", "f1_score", "avg_f1")):
            self.block.aggs.add_row()
            r = self.block.aggs.table.rowCount() - 1
            self.block.aggs.table.cellWidget(r, 0).setCurrentText(func)
            self.block.aggs.table.cellWidget(r, 1).setCurrentText(col)
            self.block.aggs.table.cellWidget(r, 2).setText(alias)
        self.add_block()
        self.block_name.setText("best")
        self.block_source.setCurrentText("run_stats")
        self.block.where.add_row()
        w = self.block.where.table
        w.cellWidget(0, 0).setCurrentText("avg_f1")
        w.cellWidget(0, 1).setCurrentText(">=")
        w.cellWidget(0, 2).setText("0.9")
        self.add_block()
        self.main_source.setCurrentText("best")
        self.join_type.setCurrentText("INNER JOIN")
        self.join_source.setCurrentText("experiments")
        keep = {"a.experiment_id", "a.avg_f1", "b.title", "b.target_attack"}
        for i in range(self.main_cols.count()):
            it = self.main_cols.item(i)
            it.setCheckState(Qt.Checked if it.text() in keep else Qt.Unchecked)
        self.main_order.add_row()
        self.main_order.table.cellWidget(0, 0).setCurrentText("a.avg_f1")
        self.main_order.table.cellWidget(0, 1).setCurrentText("DESC")
        self.execute()


# Окно представлений
class ViewsDialog(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Представления: VIEW и MATERIALIZED VIEW")
        self.setModal(True)
        self.resize(1350, 820)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.build_list_tab(), "Представления")
        self.tabs.addTab(self.build_create_tab(), "Создать представление")
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addWidget(close, alignment=Qt.AlignRight)
        self.refresh()

    def note(self, text):
        parent = self.parent()
        if parent is not None and hasattr(parent, "note"):
            parent.note(text)

    def run_ddl(self, statement, done):
        try:
            text = self.db.alter(statement)
        except DbError as e:
            show_error(self, "Ошибка — выполнен ROLLBACK", str(e))
            return False
        self.note(f"DDL: {text}")
        self.refresh()
        QMessageBox.information(self, "Готово", f"{done}\n{text}")
        return True

    # Вкладка списка
    def build_list_tab(self):
        w = QWidget()
        self.list_view = ResultView()
        self.selected = QComboBox()
        self.selected.currentIndexChanged.connect(self.show_selected)
        show = QPushButton("Показать данные")
        show.clicked.connect(self.show_data)
        self.refresh_btn = QPushButton("Обновить данные (REFRESH)")
        self.refresh_btn.clicked.connect(self.refresh_matview)
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("новое имя")
        rename = QPushButton("Переименовать")
        rename.clicked.connect(self.rename_view)
        self.cascade = QCheckBox("CASCADE")
        drop = QPushButton("Удалить")
        drop.clicked.connect(self.drop_view)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Представление:"))
        r1.addWidget(self.selected, 1)
        r1.addWidget(show)
        r1.addWidget(self.refresh_btn)
        r2 = QHBoxLayout()
        r2.addWidget(self.new_name, 1)
        r2.addWidget(rename)
        r2.addWidget(self.cascade)
        r2.addWidget(drop)
        self.definition = QPlainTextEdit()
        self.definition.setReadOnly(True)
        self.definition.setMaximumHeight(130)
        self.structure = ResultView()
        self.data = ResultView()
        self.data_sql = sql_box(40)
        top = QSplitter()
        top.addWidget(group("Список представлений схемы", self.list_view))
        top.addWidget(group("Структура (столбцы)", self.structure))
        top.setSizes([700, 600])
        bottom = group("Управление и данные", r1, r2, QLabel("Определение (SELECT, сохранённый в БД):"),
                       self.definition, self.data_sql, self.data)
        split = QSplitter(Qt.Vertical)
        split.addWidget(top)
        split.addWidget(bottom)
        split.setSizes([260, 500])
        QVBoxLayout(w).addWidget(split)
        return w

    # Вкладка создания
    def build_create_tab(self):
        w = QWidget()
        self.v_name = QLineEdit("v_run_report")
        self.v_kind = QComboBox()
        for key, title in b.VIEW_KINDS:
            self.v_kind.addItem(title, key)
        self.v_kind.currentIndexChanged.connect(self.update_kind)
        self.or_replace = QCheckBox("CREATE OR REPLACE (обновить существующее VIEW)")
        self.with_data = QCheckBox("WITH DATA (сразу заполнить; иначе WITH NO DATA)")
        self.with_data.setChecked(True)
        form = QFormLayout()
        form.addRow("Имя:", self.v_name)
        form.addRow("Вид:", self.v_kind)
        form.addRow("", self.or_replace)
        form.addRow("", self.with_data)
        self.sources = QTabWidget()
        self.sources.addTab(SelectBuilderTab4(self.db, self), "Запрос из конструктора SELECT")
        self.sources.addTab(JoinWizardTab(self.db, self), "Запрос из мастера JOIN")
        self.sources.addTab(CteBuilderTab(self.db, self), "Запрос из конструктора CTE")
        self.v_preview = sql_box(70)
        prev = QPushButton("Показать SQL")
        prev.clicked.connect(self.create_preview)
        create = QPushButton("Создать представление")
        create.setMinimumHeight(32)
        create.clicked.connect(self.create_view)
        btns = QHBoxLayout()
        btns.addWidget(prev)
        btns.addWidget(create)
        btns.addStretch()
        lay = QVBoxLayout(w)
        lay.addLayout(form)
        lay.addWidget(QLabel("Источник запроса — настройте его на нужной вкладке (можно проверить кнопкой «Выполнить»):"))
        lay.addWidget(self.sources, 1)
        lay.addWidget(self.v_preview)
        lay.addLayout(btns)
        self.update_kind()
        return w

    def update_kind(self):
        view = self.v_kind.currentData() == "VIEW"
        self.or_replace.setEnabled(view)
        self.with_data.setEnabled(not view)

    def refresh(self):
        try:
            self.views = self.db.views()
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        self.list_view.show_rows([v[:4] for v in self.views], ["Имя", "Вид", "Столбцов", "Данные"])
        current = self.selected.currentText()
        self.selected.blockSignals(True)
        self.selected.clear()
        for name, kind, *_ in self.views:
            self.selected.addItem(f"{name}  ({kind})", (name, kind))
        idx = self.selected.findText(current)
        self.selected.setCurrentIndex(max(idx, 0))
        self.selected.blockSignals(False)
        self.show_selected()

    def current(self):
        return self.selected.currentData() or (None, None)

    # Выбор представления по имени
    def select_view(self, name):
        for i in range(self.selected.count()):
            if self.selected.itemData(i)[0] == name:
                self.selected.setCurrentIndex(i)
                return True
        return False

    # Структура и определение
    def show_selected(self):
        name, kind = self.current()
        self.refresh_btn.setEnabled(kind == "MATERIALIZED VIEW")
        if not name:
            self.definition.clear()
            self.structure.show_rows([], [])
            self.data.show_rows([], [])
            return
        definition = next((v[4] for v in self.views if v[0] == name), "")
        self.definition.setPlainText(definition)
        try:
            cols = self.db.columns(name)
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        self.structure.show_rows([(c[0], c[1]) for c in cols], ["Столбец", "Тип"])
        self.data.show_rows([], [])
        self.data_sql.clear()

    def show_data(self):
        name, _ = self.current()
        if not name:
            return
        try:
            rows, cols, text = self.db.run_query(b.build_view_data(name))
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        self.data_sql.setPlainText(text)
        self.data.show_rows(rows, cols)

    def refresh_matview(self):
        name, kind = self.current()
        if name and kind == "MATERIALIZED VIEW" and self.run_ddl(b.build_refresh(name), "Данные обновлены."):
            self.select_view(name)
            self.show_data()

    def rename_view(self):
        name, kind = self.current()
        if not name:
            return
        try:
            st = b.build_view_rename(name, kind, self.new_name.text().strip())
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        new = self.new_name.text().strip()
        if self.run_ddl(st, "Представление переименовано."):
            self.new_name.clear()
            self.select_view(new)

    def drop_view(self):
        name, kind = self.current()
        if not name:
            return
        answer = QMessageBox.question(self, "Удаление", f"Удалить {kind} «{name}»?")
        if answer == QMessageBox.Yes:
            self.run_ddl(b.build_view_drop(name, kind, self.cascade.isChecked()), "Представление удалено.")

    def create_statement(self):
        query = self.sources.currentWidget().build_query()
        return b.build_create_view(self.v_name.text().strip(), self.v_kind.currentData(), query,
                                   self.or_replace.isChecked(), self.with_data.isChecked())

    def create_preview(self):
        try:
            self.v_preview.setPlainText(self.db.preview(self.create_statement()))
        except DbError as e:
            self.v_preview.setPlainText(f"-- {e}")

    def create_view(self):
        try:
            st = self.create_statement()
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        name = self.v_name.text().strip()
        if self.run_ddl(st, "Представление создано."):
            self.v_preview.clear()
            self.tabs.setCurrentIndex(0)
            self.select_view(name)
            self.show_data()
