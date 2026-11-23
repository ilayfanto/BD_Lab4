from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSplitter, QStackedWidget, QTabWidget,
    QVBoxLayout, QWidget,
)

import builders as b
from db import DbError
from lab2 import TYPE_HINTS, ResultView, RowsEditor, SelectBuilderTab, show_error, sql_box

NONE = "— нет —"


# Базовое окно вычисляемого столбца
class ComputedDialog(QDialog):
    title = ""

    def __init__(self, db, columns, parent=None):
        super().__init__(parent)
        self.db = db
        self.columns = columns
        self.result = None
        self.setWindowTitle(self.title)
        self.setModal(True)
        self.setMinimumWidth(560)
        self.alias = QLineEdit()
        self.form = QFormLayout()
        self.form.addRow("Имя нового столбца:", self.alias)
        self.preview = sql_box(70)
        check = QPushButton("Показать SQL")
        check.clicked.connect(self.show_sql)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.confirm)
        buttons.rejected.connect(self.reject)
        self.layout_ = QVBoxLayout(self)
        self.layout_.addLayout(self.form)
        self.layout_.addWidget(check, alignment=Qt.AlignLeft)
        self.layout_.addWidget(self.preview)
        self.layout_.addWidget(buttons)

    def combo(self, with_none=False):
        c = QComboBox()
        if with_none:
            c.addItem(NONE, None)
        for col in self.columns:
            c.addItem(col, col)
        return c

    def build(self):
        raise NotImplementedError

    def show_sql(self):
        try:
            self.preview.setPlainText(self.db.preview(self.build()))
        except DbError as e:
            self.preview.setPlainText(f"-- {e}")

    def confirm(self):
        alias = self.alias.text().strip()
        try:
            b.check_name(alias, "имя столбца")
            expr = self.build()
            text = self.db.preview(expr)
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        self.result = (alias, expr, text)
        self.accept()


# Конструктор CASE
class CaseDialog(ComputedDialog):
    title = "Конструктор CASE WHEN … THEN … ELSE … END"

    def __init__(self, db, columns, parent=None):
        super().__init__(db, columns, parent)
        self.alias.setText("category")
        self.whens = RowsEditor(["Столбец", "Оператор", "Значение", "THEN (результат)"], ["combo", "combo", "edit", "edit"])
        self.whens.set_options(0, columns)
        self.whens.set_options(1, b.WHERE_OPS)
        self.whens.setMinimumHeight(180)
        self.whens.add_row()
        self.use_else = QCheckBox("ELSE")
        self.use_else.setChecked(True)
        self.else_value = QLineEdit("другое")
        er = QHBoxLayout()
        er.addWidget(self.use_else)
        er.addWidget(self.else_value, 1)
        self.form.addRow("Условия WHEN:", self.whens)
        self.form.addRow("Иначе:", er)
        self.form.addRow("", QLabel("Условия проверяются сверху вниз; срабатывает первое истинное."))

    def build(self):
        whens = [w for w in self.whens.values() if w[0]]
        else_value = self.else_value.text() if self.use_else.isChecked() else None
        return b.case_expr(whens, else_value)


# Конструктор COALESCE
class CoalesceDialog(ComputedDialog):
    title = "COALESCE — подстановка значения вместо NULL"

    def __init__(self, db, columns, parent=None):
        super().__init__(db, columns, parent)
        self.alias.setText("value_or_default")
        self.column = self.combo()
        self.column2 = self.combo(with_none=True)
        self.value = QLineEdit("нет данных")
        self.as_text = QCheckBox("Привести к тексту (чтобы подставлять текст вместо чисел/дат)")
        self.as_text.setChecked(True)
        self.form.addRow("Столбец:", self.column)
        self.form.addRow("Запасной столбец:", self.column2)
        self.form.addRow("Значение вместо NULL:", self.value)
        self.form.addRow("", self.as_text)
        self.form.addRow("", QLabel("COALESCE возвращает первый аргумент, который не NULL."))

    def build(self):
        return b.coalesce_expr(self.column.currentData(), self.value.text(), self.column2.currentData(),
                               self.as_text.isChecked())


# Конструктор NULLIF
class NullifDialog(ComputedDialog):
    title = "NULLIF — замена совпадающего значения на NULL"

    def __init__(self, db, columns, parent=None):
        super().__init__(db, columns, parent)
        self.alias.setText("value_or_null")
        self.column = self.combo()
        self.value = QLineEdit()
        self.as_text = QCheckBox("Сравнивать как текст")
        self.form.addRow("Столбец:", self.column)
        self.form.addRow("Если равно:", self.value)
        self.form.addRow("", self.as_text)
        self.form.addRow("", QLabel("NULLIF(a, b) возвращает NULL, если a = b, иначе a."))

    def build(self):
        return b.nullif_expr(self.column.currentData(), self.value.text(), self.as_text.isChecked())


# Список вычисляемых столбцов
class ComputedEditor(QWidget):
    def __init__(self, db, columns_provider, on_change=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.columns_provider = columns_provider
        self.on_change = on_change
        self.items = []
        self.list = QListWidget()
        self.list.setMinimumHeight(90)
        btns = QHBoxLayout()
        for caption, cls in (("CASE…", CaseDialog), ("COALESCE…", CoalesceDialog), ("NULLIF…", NullifDialog)):
            btn = QPushButton(caption)
            btn.clicked.connect(lambda _=False, c=cls: self.add(c))
            btns.addWidget(btn)
        rem = QPushButton("Удалить")
        rem.clicked.connect(self.remove)
        btns.addWidget(rem)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(btns)
        layout.addWidget(self.list)

    def add(self, cls):
        dialog = cls(self.db, self.columns_provider(), self)
        if dialog.exec() and dialog.result:
            alias, expr, text = dialog.result
            if alias in [a for a, _, _ in self.items]:
                show_error(self, "Ошибка", f"Столбец «{alias}» уже добавлен.")
                return
            self.items.append(dialog.result)
            self.list.addItem(f"{alias} = {text}")
            self.changed()

    def remove(self):
        r = self.list.currentRow()
        if r >= 0:
            self.list.takeItem(r)
            self.items.pop(r)
            self.changed()

    def clear(self):
        self.items.clear()
        self.list.clear()

    def changed(self):
        if self.on_change:
            self.on_change()

    def computed(self):
        return [(a, e) for a, e, _ in self.items]

    def aliases(self):
        return [a for a, _, _ in self.items]


# Конструктор SELECT с CASE / COALESCE / NULLIF
class SelectBuilderTab3(SelectBuilderTab):
    def __init__(self, db, parent=None):
        super().__init__(db, parent)
        self.calc = ComputedEditor(db, lambda: db.column_names(self.table.currentText()), self.sync_aliases)
        box = QGroupBox("Вычисляемые столбцы: CASE, COALESCE, NULLIF")
        QVBoxLayout(box).addWidget(self.calc)
        self.cfg_layout.insertWidget(3, box)

    def load_columns(self):
        super().load_columns()
        if hasattr(self, "calc"):
            self.calc.clear()

    # Псевдонимы в GROUP BY и ORDER BY
    def sync_aliases(self):
        cols = self.db.column_names(self.table.currentText())
        aliases = self.calc.aliases()
        existing = [self.group.item(i).text() for i in range(self.group.count())]
        for i in reversed(range(self.group.count())):
            if self.group.item(i).text() not in cols + aliases:
                self.group.takeItem(i)
        for a in aliases:
            if a not in existing:
                it = QListWidgetItem(a)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Unchecked)
                self.group.addItem(it)
        self.order.set_options(0, cols + aliases)

    def computed(self):
        return self.calc.computed()


PRESETS = [
    ("Модели, у которых есть эксперименты (EXISTS, коррелированный)", "models",
     dict(kind="EXISTS", inner_table="experiments", correlated=True, corr_inner="model_id", corr_outer="model_id")),
    ("Модели без экспериментов (NOT EXISTS, коррелированный)", "models",
     dict(kind="NOT EXISTS", inner_table="experiments", correlated=True, corr_inner="model_id", corr_outer="model_id")),
    ("Модели из экспериментов по mixed (IN)", "models",
     dict(kind="IN", outer_col="model_id", inner_table="experiments", inner_col="model_id",
          filter_col="target_attack", filter_op="=", filter_val="mixed")),
    ("Запуски с F1 выше среднего (скалярный подзапрос AVG)", "runs",
     dict(kind="SCALAR", outer_col="f1_score", op=">", inner_table="runs", inner_col="f1_score", agg="AVG")),
    ("Запуски не хуже среднего по своему эксперименту (коррелированный)", "runs",
     dict(kind="SCALAR", outer_col="f1_score", op=">=", inner_table="runs", inner_col="f1_score", agg="AVG",
          correlated=True, corr_inner="experiment_id", corr_outer="experiment_id")),
    ("Лучший завершённый запуск (>= ALL)", "runs",
     dict(kind="ALL", outer_col="f1_score", op=">=", inner_table="runs", inner_col="f1_score",
          filter_col="status", filter_op="=", filter_val="completed")),
    ("Эксперименты на больших датасетах (= ANY, records > 1 млн)", "experiments",
     dict(kind="ANY", outer_col="dataset_id", op="=", inner_table="datasets", inner_col="dataset_id",
          filter_col="records", filter_op=">", filter_val="1000000")),
]


# Фильтры на основе подзапросов
class SubqueryTab(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.tables = db.selectables()
        self.cols = {t: db.column_names(t) for t in self.tables}
        self.fks = db.foreign_keys()
        self.conditions = []

        self.outer = QComboBox()
        self.outer.addItems(self.tables)
        self.outer.currentTextChanged.connect(self.outer_changed)
        self.preset = QComboBox()
        self.preset.addItem("— выберите пример —", None)
        for i, (title, _, _) in enumerate(PRESETS):
            self.preset.addItem(title, i)
        apply_preset = QPushButton("Подставить пример")
        apply_preset.clicked.connect(self.apply_preset)

        self.kind = QComboBox()
        for key, title in b.SUB_KINDS:
            self.kind.addItem(title, key)
        self.kind.currentIndexChanged.connect(self.update_fields)
        self.outer_col = QComboBox()
        self.op = QComboBox()
        self.op.addItems(b.COMPARE_OPS)
        self.inner = QComboBox()
        self.inner.addItems(self.tables)
        self.inner.currentTextChanged.connect(self.inner_changed)
        self.inner_col = QComboBox()
        self.agg = QComboBox()
        self.agg.addItems([f for f in b.AGG_FUNCS if f != "STRING_AGG"])
        self.filter_col = QComboBox()
        self.filter_op = QComboBox()
        self.filter_op.addItems(b.WHERE_OPS)
        self.filter_val = QLineEdit()
        self.correlated = QCheckBox("Коррелированный подзапрос: связать с внешней строкой")
        self.correlated.toggled.connect(self.update_fields)
        self.corr_inner = QComboBox()
        self.corr_outer = QComboBox()

        frow = QHBoxLayout()
        frow.addWidget(self.filter_col, 2)
        frow.addWidget(self.filter_op, 1)
        frow.addWidget(self.filter_val, 2)
        crow = QHBoxLayout()
        crow.addWidget(QLabel("i."))
        crow.addWidget(self.corr_inner, 1)
        crow.addWidget(QLabel("= o."))
        crow.addWidget(self.corr_outer, 1)
        self.corr_row = QWidget()
        self.corr_row.setLayout(crow)

        self.form = QFormLayout()
        self.form.addRow("Вид условия:", self.kind)
        self.form.addRow("Столбец внешней таблицы o.:", self.outer_col)
        self.form.addRow("Оператор сравнения:", self.op)
        self.form.addRow("Таблица подзапроса (i):", self.inner)
        self.form.addRow("Агрегат подзапроса:", self.agg)
        self.form.addRow("Столбец подзапроса i.:", self.inner_col)
        self.form.addRow("Фильтр внутри подзапроса:", frow)
        self.form.addRow("", self.correlated)
        self.form.addRow("Связь:", self.corr_row)
        add = QPushButton("Добавить условие")
        add.clicked.connect(self.add_condition)
        cond_box = QGroupBox("Новое условие с подзапросом")
        cl = QVBoxLayout(cond_box)
        cl.addLayout(self.form)
        cl.addWidget(add)

        self.cond_list = QListWidget()
        self.cond_list.setMinimumHeight(110)
        self.join = QComboBox()
        self.join.addItems(["AND", "OR"])
        rem = QPushButton("Удалить выбранное")
        rem.clicked.connect(self.remove_condition)
        clr = QPushButton("Очистить")
        clr.clicked.connect(self.clear_conditions)
        run = QPushButton("Выполнить выборку")
        run.setMinimumHeight(32)
        run.clicked.connect(self.execute)
        lb = QHBoxLayout()
        lb.addWidget(QLabel("Объединять через:"))
        lb.addWidget(self.join)
        lb.addStretch()
        lb.addWidget(rem)
        lb.addWidget(clr)
        list_box = QGroupBox("Условия отбора (WHERE)")
        ll = QVBoxLayout(list_box)
        ll.addWidget(self.cond_list)
        ll.addLayout(lb)

        left = QWidget()
        lv = QVBoxLayout(left)
        top = QFormLayout()
        top.addRow("Внешняя таблица (o):", self.outer)
        pr = QHBoxLayout()
        pr.addWidget(self.preset, 1)
        pr.addWidget(apply_preset)
        top.addRow("Пример:", pr)
        lv.addLayout(top)
        lv.addWidget(cond_box)
        lv.addWidget(list_box)
        lv.addWidget(run)
        lv.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        scroll.setMinimumWidth(560)

        self.preview = sql_box(90)
        self.result = ResultView()
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(QLabel("Сгенерированный SQL:"))
        rv.addWidget(self.preview)
        rv.addWidget(self.result)
        split = QSplitter()
        split.addWidget(scroll)
        split.addWidget(right)
        split.setSizes([580, 700])
        QVBoxLayout(self).addWidget(split)

        self.outer_changed()
        self.inner_changed()
        self.update_fields()

    @staticmethod
    def fill(combo, items, with_none=False):
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        if with_none:
            combo.addItem(NONE)
        combo.addItems(items)
        if current in items:
            combo.setCurrentText(current)
        combo.blockSignals(False)

    def outer_changed(self):
        cols = self.cols.get(self.outer.currentText(), [])
        self.fill(self.outer_col, cols)
        self.fill(self.corr_outer, cols)
        self.clear_conditions()
        self.suggest_corr()

    def inner_changed(self):
        cols = self.cols.get(self.inner.currentText(), [])
        self.fill(self.inner_col, cols)
        self.fill(self.corr_inner, cols)
        self.fill(self.filter_col, cols, with_none=True)
        self.suggest_corr()

    # Подсказка связи по внешним ключам
    def suggest_corr(self):
        o, i = self.outer.currentText(), self.inner.currentText()
        if o == i:
            return
        for ct, cc, rt, rc in self.fks:
            if ct == i and rt == o:
                self.corr_inner.setCurrentText(cc)
                self.corr_outer.setCurrentText(rc)
                return
            if ct == o and rt == i:
                self.corr_inner.setCurrentText(rc)
                self.corr_outer.setCurrentText(cc)
                return

    # Видимость полей под вид условия
    def update_fields(self):
        kind = self.kind.currentData()
        exists = kind in ("EXISTS", "NOT EXISTS")
        self.form.setRowVisible(self.outer_col, not exists)
        self.form.setRowVisible(self.op, kind in ("ANY", "ALL", "SCALAR"))
        self.form.setRowVisible(self.agg, kind == "SCALAR")
        self.form.setRowVisible(self.inner_col, not exists)
        self.form.setRowVisible(self.corr_row, self.correlated.isChecked())

    def current(self):
        fcol = self.filter_col.currentText()
        return dict(
            kind=self.kind.currentData(), outer_col=self.outer_col.currentText(), op=self.op.currentText(),
            inner_table=self.inner.currentText(), inner_col=self.inner_col.currentText(), agg=self.agg.currentText(),
            filter_col=None if fcol == NONE else fcol, filter_op=self.filter_op.currentText(),
            filter_val=self.filter_val.text(), correlated=self.correlated.isChecked(),
            corr_inner=self.corr_inner.currentText(), corr_outer=self.corr_outer.currentText(),
        )

    def add_condition(self):
        try:
            cond = b.build_subquery_condition(self.current())
            text = self.db.preview(cond)
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        self.conditions.append(cond)
        self.cond_list.addItem(text)

    def remove_condition(self):
        r = self.cond_list.currentRow()
        if r >= 0:
            self.cond_list.takeItem(r)
            self.conditions.pop(r)

    def clear_conditions(self):
        self.conditions.clear()
        self.cond_list.clear()

    # Пример
    def apply_preset(self):
        idx = self.preset.currentData()
        if idx is None:
            return
        _, table, c = PRESETS[idx]
        self.outer.setCurrentText(table)
        self.kind.setCurrentIndex(self.kind.findData(c["kind"]))
        self.inner.setCurrentText(c["inner_table"])
        if c.get("outer_col"):
            self.outer_col.setCurrentText(c["outer_col"])
        self.op.setCurrentText(c.get("op", "="))
        if c.get("inner_col"):
            self.inner_col.setCurrentText(c["inner_col"])
        self.agg.setCurrentText(c.get("agg", "AVG"))
        self.filter_col.setCurrentText(c.get("filter_col") or NONE)
        self.filter_op.setCurrentText(c.get("filter_op", "="))
        self.filter_val.setText(c.get("filter_val", ""))
        self.correlated.setChecked(bool(c.get("correlated")))
        if c.get("correlated"):
            self.corr_inner.setCurrentText(c["corr_inner"])
            self.corr_outer.setCurrentText(c["corr_outer"])
        self.clear_conditions()
        self.add_condition()
        self.execute()

    def execute(self):
        try:
            q = b.build_subquery_select(self.outer.currentText(), self.conditions, self.join.currentText())
            rows, cols, text = self.db.run_query(q)
        except DbError as e:
            show_error(self, "Ошибка выборки", str(e))
            return
        self.preview.setPlainText(text)
        self.result.show_rows(rows, cols)


# Окно пользовательских типов
class TypesDialog(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Пользовательские типы данных")
        self.setModal(True)
        self.resize(1200, 720)
        tabs = QTabWidget()
        tabs.addTab(self.build_manage_tab(), "Существующие типы")
        tabs.addTab(self.build_create_tab(), "Создать тип")
        tabs.addTab(self.build_table_tab(), "Таблица с пользовательскими типами")
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(close, alignment=Qt.AlignRight)
        self.refresh()

    def type_options(self):
        return TYPE_HINTS + [t for t in self.db.user_type_names() if t not in TYPE_HINTS]

    def note(self, text):
        parent = self.parent()
        if parent is not None and hasattr(parent, "note"):
            parent.note(text)

    # Выполнение DDL
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

    # Обновление всех списков
    def refresh(self):
        try:
            self.types = self.db.user_types()
            self.composites = self.db.composite_fields()
            tables = self.db.tables()
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        self.types_view.show_rows(self.types, ["Тип", "Вид", "Значения / поля / определение", "Используется в"])
        current = self.m_type.currentText()
        self.m_type.blockSignals(True)
        self.m_type.clear()
        for name, kind, _, _ in self.types:
            self.m_type.addItem(f"{name}  ({kind})", (name, kind))
        idx = self.m_type.findText(current)
        self.m_type.setCurrentIndex(max(idx, 0))
        self.m_type.blockSignals(False)
        self.type_selected()
        options = self.type_options()
        for combo in (self.m_attr_type, self.d_base):
            text = combo.currentText()
            combo.clear()
            combo.addItems(options)
            combo.setCurrentText(text)
        self.c_fields.set_options(1, options)
        self.t_columns.set_options(1, options)
        t = self.data_table.currentText()
        self.data_table.blockSignals(True)
        self.data_table.clear()
        self.data_table.addItems(tables)
        if t in tables:
            self.data_table.setCurrentText(t)
        self.data_table.blockSignals(False)
        self.build_data_form()

    # Вкладка управления
    def build_manage_tab(self):
        w = QWidget()
        self.types_view = ResultView()
        self.m_type = QComboBox()
        self.m_type.currentIndexChanged.connect(self.type_selected)
        self.m_op = QComboBox()
        for key, title in b.TYPE_OPS:
            self.m_op.addItem(title, key)
        self.m_op.currentIndexChanged.connect(self.update_manage_fields)
        self.m_value = QLineEdit()
        self.m_position = QComboBox()
        self.m_position.addItems(["в конец", "BEFORE", "AFTER"])
        self.m_ref = QComboBox()
        self.m_name = QLineEdit()
        self.m_attr_type = QComboBox()
        self.m_attr_type.setEditable(True)
        self.m_attr = QComboBox()
        self.m_cascade = QCheckBox("CASCADE (удалить зависимые столбцы)")
        self.m_form = QFormLayout()
        self.m_form.addRow("Тип:", self.m_type)
        self.m_form.addRow("Действие:", self.m_op)
        self.m_form.addRow("Значение ENUM:", self.m_ref)
        self.m_form.addRow("Новое значение:", self.m_value)
        self.m_form.addRow("Позиция:", self.m_position)
        self.m_form.addRow("Имя:", self.m_name)
        self.m_form.addRow("Тип поля:", self.m_attr_type)
        self.m_form.addRow("Поле:", self.m_attr)
        self.m_form.addRow("", self.m_cascade)
        for sig in (self.m_value.textChanged, self.m_name.textChanged, self.m_position.currentIndexChanged,
                    self.m_ref.currentIndexChanged, self.m_attr.currentIndexChanged,
                    self.m_attr_type.currentTextChanged, self.m_cascade.toggled):
            sig.connect(self.manage_preview)
        self.m_preview = sql_box(70)
        run = QPushButton("Выполнить")
        run.clicked.connect(self.manage_execute)
        box = QGroupBox("Управление типом")
        bl = QVBoxLayout(box)
        bl.addLayout(self.m_form)
        bl.addWidget(self.m_preview)
        bl.addWidget(run)
        bl.addStretch()
        split = QSplitter()
        split.addWidget(self.types_view)
        split.addWidget(box)
        split.setSizes([760, 420])
        QVBoxLayout(w).addWidget(split)
        return w

    def selected_type(self):
        return self.m_type.currentData() or (None, None)

    def type_selected(self):
        name, kind = self.selected_type()
        self.m_ref.clear()
        self.m_attr.clear()
        if kind == "ENUM":
            self.m_ref.addItems(self.db.enum_labels(name))
        if kind == "Составной":
            self.m_attr.addItems(self.composites.get(name, []))
        self.update_manage_fields()

    def update_manage_fields(self):
        op = self.m_op.currentData()
        visible = {
            "enum_add": {self.m_value, self.m_position, self.m_ref},
            "enum_rename": {self.m_ref, self.m_value},
            "attr_add": {self.m_name, self.m_attr_type},
            "attr_drop": {self.m_attr, self.m_cascade},
            "rename": {self.m_name},
            "drop": {self.m_cascade},
        }[op]
        for widget in (self.m_ref, self.m_value, self.m_position, self.m_name, self.m_attr_type, self.m_attr, self.m_cascade):
            self.m_form.setRowVisible(widget, widget in visible)
        self.m_form.labelForField(self.m_ref).setText("Относительно значения:" if op == "enum_add" else "Значение ENUM:")
        self.m_form.labelForField(self.m_name).setText("Новое имя типа:" if op == "rename" else "Имя поля:")
        self.manage_preview()

    def manage_statement(self):
        name, kind = self.selected_type()
        if not name:
            raise DbError("Нет пользовательских типов.")
        op = self.m_op.currentData()
        if op.startswith("enum") and kind != "ENUM":
            raise DbError("Это действие только для ENUM.")
        if op.startswith("attr") and kind != "Составной":
            raise DbError("Это действие только для составных типов.")
        position = self.m_position.currentText()
        p = {"value": self.m_value.text(), "position": position if position != "в конец" else None,
             "ref": self.m_ref.currentText(), "name": self.m_name.text().strip(),
             "type": self.m_attr_type.currentText(), "attr": self.m_attr.currentText(),
             "cascade": self.m_cascade.isChecked()}
        return b.build_alter_type(op, name, "domain" if kind == "DOMAIN" else "type", p)

    def manage_preview(self):
        try:
            self.m_preview.setPlainText(self.db.preview(self.manage_statement()))
        except DbError as e:
            self.m_preview.setPlainText(f"-- {e}")

    def manage_execute(self):
        try:
            st = self.manage_statement()
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        if self.run_ddl(st, "Тип изменён."):
            self.m_value.clear()
            self.m_name.clear()

    # Вкладка создания типа
    def build_create_tab(self):
        w = QWidget()
        self.c_kind = QComboBox()
        for key, title in b.TYPE_KINDS:
            self.c_kind.addItem(title, key)
        self.c_name = QLineEdit()
        self.c_name.setPlaceholderText("например: severity, contact_t, probability")

        enum_page = QWidget()
        self.e_values = QListWidget()
        self.e_new = QLineEdit()
        self.e_new.setPlaceholderText("новое значение и Enter")
        self.e_new.returnPressed.connect(self.enum_add_value)
        e_add = QPushButton("Добавить")
        e_add.clicked.connect(self.enum_add_value)
        e_del = QPushButton("Удалить")
        e_del.clicked.connect(lambda: self.e_values.takeItem(self.e_values.currentRow()))
        er = QHBoxLayout()
        er.addWidget(self.e_new, 1)
        er.addWidget(e_add)
        er.addWidget(e_del)
        el = QVBoxLayout(enum_page)
        el.addWidget(QLabel("Значения перечисления (по порядку):"))
        el.addWidget(self.e_values)
        el.addLayout(er)

        comp_page = QWidget()
        self.c_fields = RowsEditor(["Поле", "Тип"], ["edit", "ecombo"])
        self.c_fields.add_row()
        cl = QVBoxLayout(comp_page)
        cl.addWidget(QLabel("Поля составного типа:"))
        cl.addWidget(self.c_fields)

        dom_page = QWidget()
        self.d_base = QComboBox()
        self.d_base.setEditable(True)
        self.d_default = QLineEdit()
        self.d_not_null = QCheckBox("NOT NULL")
        self.d_check = QLineEdit()
        self.d_check.setPlaceholderText("VALUE BETWEEN 0 AND 1   или   VALUE SIMILAR TO '%@%.%'")
        dl = QFormLayout(dom_page)
        dl.addRow("Базовый тип:", self.d_base)
        dl.addRow("DEFAULT:", self.d_default)
        dl.addRow("", self.d_not_null)
        dl.addRow("CHECK:", self.d_check)

        self.c_stack = QStackedWidget()
        for page in (enum_page, comp_page, dom_page):
            self.c_stack.addWidget(page)
        self.c_kind.currentIndexChanged.connect(self.c_stack.setCurrentIndex)
        self.c_preview = sql_box(70)
        prev = QPushButton("Показать SQL")
        prev.clicked.connect(self.create_preview)
        create = QPushButton("Создать тип")
        create.setMinimumHeight(32)
        create.clicked.connect(self.create_type)
        form = QFormLayout()
        form.addRow("Вид типа:", self.c_kind)
        form.addRow("Имя типа:", self.c_name)
        btns = QHBoxLayout()
        btns.addWidget(prev)
        btns.addWidget(create)
        btns.addStretch()
        layout = QVBoxLayout(w)
        layout.addLayout(form)
        layout.addWidget(self.c_stack)
        layout.addWidget(self.c_preview)
        layout.addLayout(btns)
        return w

    def enum_add_value(self):
        value = self.e_new.text().strip()
        if value:
            self.e_values.addItem(value)
            self.e_new.clear()

    def create_statement(self):
        kind = self.c_kind.currentData()
        values = [self.e_values.item(i).text() for i in range(self.e_values.count())]
        fields = [(f.strip(), t) for f, t in self.c_fields.values()]
        return b.build_create_type(kind, self.c_name.text().strip(), values=values, fields=fields,
                                   base=self.d_base.currentText(), default=self.d_default.text(),
                                   not_null=self.d_not_null.isChecked(), check=self.d_check.text().strip())

    def create_preview(self):
        try:
            self.c_preview.setPlainText(self.db.preview(self.create_statement()))
        except DbError as e:
            self.c_preview.setPlainText(f"-- {e}")

    def create_type(self):
        try:
            st = self.create_statement()
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        if self.run_ddl(st, "Тип создан."):
            self.c_name.clear()
            self.e_values.clear()
            self.c_fields.clear()
            self.c_fields.add_row()

    # Вкладка таблицы с пользовательскими типами
    def build_table_tab(self):
        w = QWidget()
        self.t_name = QLineEdit()
        self.t_name.setPlaceholderText("например: incidents")
        self.t_id = QCheckBox("Добавить столбец id (IDENTITY, PRIMARY KEY)")
        self.t_id.setChecked(True)
        self.t_columns = RowsEditor(["Столбец", "Тип", "NOT NULL"], ["edit", "ecombo", "combo"])
        self.t_columns.set_options(2, ["нет", "да"])
        self.t_columns.add_row()
        self.t_preview = sql_box(60)
        prev = QPushButton("Показать SQL")
        prev.clicked.connect(self.table_preview)
        create = QPushButton("Создать таблицу")
        create.clicked.connect(self.create_table)
        tf = QFormLayout()
        tf.addRow("Имя таблицы:", self.t_name)
        tf.addRow("", self.t_id)
        tbtns = QHBoxLayout()
        tbtns.addWidget(prev)
        tbtns.addWidget(create)
        tbtns.addStretch()
        create_box = QGroupBox("CREATE TABLE")
        cl = QVBoxLayout(create_box)
        cl.addLayout(tf)
        cl.addWidget(self.t_columns)
        cl.addWidget(self.t_preview)
        cl.addLayout(tbtns)

        self.data_table = QComboBox()
        self.data_table.currentTextChanged.connect(self.build_data_form)
        self.data_form_host = QWidget()
        self.data_form = QFormLayout(self.data_form_host)
        self.data_inputs = {}
        insert = QPushButton("Вставить строку (INSERT)")
        insert.clicked.connect(self.insert_row)
        show = QPushButton("Показать данные")
        show.clicked.connect(self.show_data)
        self.data_preview = sql_box(50)
        self.data_view = ResultView()
        db_ = QHBoxLayout()
        db_.addWidget(insert)
        db_.addWidget(show)
        db_.addStretch()
        data_box = QGroupBox("Данные таблицы")
        dl = QVBoxLayout(data_box)
        top = QFormLayout()
        top.addRow("Таблица:", self.data_table)
        dl.addLayout(top)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.data_form_host)
        scroll.setMaximumHeight(200)
        dl.addWidget(scroll)
        dl.addLayout(db_)
        dl.addWidget(self.data_preview)
        dl.addWidget(self.data_view)

        split = QSplitter()
        split.addWidget(create_box)
        split.addWidget(data_box)
        split.setSizes([480, 700])
        QVBoxLayout(w).addWidget(split)
        return w

    def table_statement(self):
        cols = [(c.strip(), t, nn == "да") for c, t, nn in self.t_columns.values()]
        return b.build_create_table(self.t_name.text().strip(), cols, self.t_id.isChecked())

    def table_preview(self):
        try:
            self.t_preview.setPlainText(self.db.preview(self.table_statement()))
        except DbError as e:
            self.t_preview.setPlainText(f"-- {e}")

    def create_table(self):
        try:
            st = self.table_statement()
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        name = self.t_name.text().strip()
        if self.run_ddl(st, "Таблица создана."):
            self.data_table.setCurrentText(name)
            self.t_name.clear()

    # Форма ввода под столбцы таблицы
    def build_data_form(self):
        while self.data_form.rowCount():
            self.data_form.removeRow(0)
        self.data_inputs = {}
        table = self.data_table.currentText()
        if not table:
            return
        try:
            cols = self.db.columns(table)
        except DbError:
            return
        enums = {name for name, kind, _, _ in self.types if kind == "ENUM"}
        for name, typ, nullable, default in cols:
            if typ in enums:
                w = QComboBox()
                w.addItem("")
                w.addItems(self.db.enum_labels(typ))
            else:
                w = QLineEdit()
                if typ in self.composites:
                    w.setPlaceholderText("(" + ",".join(self.composites[typ]) + ")")
                elif typ.endswith("[]"):
                    w.setPlaceholderText("{значение1,значение2}")
                elif default:
                    w.setPlaceholderText(f"по умолчанию: {default}")
            label = f"{name} ({typ}){'' if nullable else ' *'}:"
            self.data_form.addRow(label, w)
            self.data_inputs[name] = w

    def insert_row(self):
        values = {n: (w.currentText() if isinstance(w, QComboBox) else w.text()) for n, w in self.data_inputs.items()}
        try:
            st = b.build_insert(self.data_table.currentText(), values)
            text = self.db.execute(st, "INSERT")
        except DbError as e:
            show_error(self, "Ошибка вставки — выполнен ROLLBACK", str(e))
            return
        self.note(text)
        self.data_preview.setPlainText(text)
        for w in self.data_inputs.values():
            w.setCurrentIndex(0) if isinstance(w, QComboBox) else w.clear()
        self.show_data()

    def show_data(self):
        table = self.data_table.currentText()
        try:
            cols = [(c[0], c[1]) for c in self.db.columns(table)]
            rows, names, text = self.db.run_query(b.build_table_view(table, cols, self.composites))
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        self.data_preview.setPlainText(text)
        self.data_view.show_rows(rows, names)
