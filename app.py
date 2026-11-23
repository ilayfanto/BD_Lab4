import sys
from datetime import datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from db import Database, DbError, load_config, log
from lab2 import AlterDialog, JoinWizardTab, SearchTab, StringsDialog
from lab3 import SubqueryTab, TypesDialog
from lab4 import CteBuilderTab, SelectBuilderTab4, ViewsDialog


# Пустая строка в NULL
def val(widget):
    text = widget.text().strip()
    return text or None


# Строка через запятую в массив
def to_array(widget):
    return [p.strip() for p in widget.text().split(",") if p.strip()]


# Окно ошибки
def show_error(parent, title, message):
    QMessageBox.critical(parent, title, message)


# Базовая форма ввода
class BaseForm(QDialog):
    title = ""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle(self.title)
        self.setModal(True)
        self.setMinimumWidth(460)
        self.form = QFormLayout()
        buttons = QDialogButtonBox()
        self.save_btn = buttons.addButton("Сохранить", QDialogButtonBox.AcceptRole)
        buttons.addButton("Закрыть", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(buttons)

    # Сохранение
    def save(self):
        try:
            new_id = self.insert()
        except DbError as e:
            show_error(self, "Ошибка вставки — выполнен ROLLBACK", str(e))
            return
        QMessageBox.information(self, "Готово", f"Запись добавлена (ID = {new_id}).")
        self.accept()

    def insert(self):
        raise NotImplementedError


# Форма модели
class ModelForm(BaseForm):
    title = "Добавить модель"

    def __init__(self, db, parent=None):
        super().__init__(db, parent)
        self.name = QLineEdit()
        self.family = QComboBox()
        self.family.addItems(db.enum_values("model_family"))
        self.version = QLineEdit("1.0")
        self.prod = QCheckBox("Используется в продакшене")
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("baseline, gpu, edge")
        self.form.addRow("Название*:", self.name)
        self.form.addRow("Семейство (ENUM)*:", self.family)
        self.form.addRow("Версия*:", self.version)
        self.form.addRow("", self.prod)
        self.form.addRow("Теги (массив):", self.tags)

    def insert(self):
        return self.db.add_model(val(self.name), self.family.currentText(), val(self.version),
                                 self.prod.isChecked(), to_array(self.tags))


# Форма датасета
class DatasetForm(BaseForm):
    title = "Добавить датасет"

    def __init__(self, db, parent=None):
        super().__init__(db, parent)
        self.name = QLineEdit()
        self.source = QLineEdit()
        self.attacks = QListWidget()
        self.attacks.setMaximumHeight(150)
        for a in db.enum_values("attack_type"):
            item = QListWidgetItem(a)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.attacks.addItem(item)
        self.records = QLineEdit()
        self.collected = QLineEdit(QDate.currentDate().toString("yyyy-MM-dd"))
        self.form.addRow("Название*:", self.name)
        self.form.addRow("Источник*:", self.source)
        self.form.addRow("Типы атак (ENUM[])*:", self.attacks)
        self.form.addRow("Число записей*:", self.records)
        self.form.addRow("Дата сбора*:", self.collected)

    def insert(self):
        attacks = [self.attacks.item(i).text() for i in range(self.attacks.count())
                   if self.attacks.item(i).checkState() == Qt.Checked]
        return self.db.add_dataset(val(self.name), val(self.source), attacks,
                                   val(self.records), val(self.collected))


# Форма эксперимента
class ExperimentForm(BaseForm):
    title = "Добавить эксперимент"

    def __init__(self, db, parent=None):
        super().__init__(db, parent)
        self.title_edit = QLineEdit()
        self.model = QComboBox()
        for mid, name in db.list_models():
            self.model.addItem(f"{mid}: {name}", mid)
        self.dataset = QComboBox()
        self.dataset.addItem("— не указан —", None)
        for did, name in db.list_datasets():
            self.dataset.addItem(f"{did}: {name}", did)
        self.attack = QComboBox()
        self.attack.addItems(db.enum_values("attack_type"))
        self.started = QLineEdit(QDate.currentDate().toString("yyyy-MM-dd"))
        self.descr = QPlainTextEdit()
        self.descr.setMaximumHeight(80)
        self.form.addRow("Название*:", self.title_edit)
        self.form.addRow("Модель (FK)*:", self.model)
        self.form.addRow("Датасет (FK):", self.dataset)
        self.form.addRow("Целевая атака (ENUM)*:", self.attack)
        self.form.addRow("Дата начала*:", self.started)
        self.form.addRow("Описание:", self.descr)

    def insert(self):
        return self.db.add_experiment(val(self.title_edit), self.model.currentData(), self.dataset.currentData(),
                                      self.attack.currentText(), val(self.started),
                                      self.descr.toPlainText().strip() or None)


# Форма запуска
class RunForm(BaseForm):
    title = "Добавить запуск"

    def __init__(self, db, parent=None):
        super().__init__(db, parent)
        self.experiment = QComboBox()
        for eid, name in db.list_experiments():
            self.experiment.addItem(f"{eid}: {name}", eid)
        self.run_no = QLineEdit("1")
        self.status = QComboBox()
        self.status.addItems(db.enum_values("run_status"))
        self.started = QLineEdit(datetime.now().strftime("%Y-%m-%d %H:%M"))
        self.precision = QLineEdit()
        self.recall = QLineEdit()
        self.f1 = QLineEdit()
        self.latency = QLineEdit()
        self.epochs = QLineEdit("10")
        self.gpu = QCheckBox("Обучение на GPU")
        self.features = QLineEdit()
        self.features.setPlaceholderText("pkt_rate, syn_ratio, ttl")
        for w in (self.precision, self.recall, self.f1):
            w.setPlaceholderText("0..1")
        self.form.addRow("Эксперимент (FK)*:", self.experiment)
        self.form.addRow("Номер запуска*:", self.run_no)
        self.form.addRow("Статус (ENUM)*:", self.status)
        self.form.addRow("Время запуска*:", self.started)
        self.form.addRow("Precision:", self.precision)
        self.form.addRow("Recall:", self.recall)
        self.form.addRow("F1:", self.f1)
        self.form.addRow("Задержка, мс:", self.latency)
        self.form.addRow("Эпохи*:", self.epochs)
        self.form.addRow("", self.gpu)
        self.form.addRow("Признаки (массив)*:", self.features)

    def insert(self):
        return self.db.add_run(self.experiment.currentData(), val(self.run_no), self.status.currentText(),
                               val(self.started), val(self.precision), val(self.recall), val(self.f1),
                               val(self.latency), val(self.epochs), self.gpu.isChecked(), to_array(self.features))


# Окно выбора формы ввода
class InsertDialog(QDialog):
    FORMS = [("Модель ИИ", ModelForm), ("Датасет трафика", DatasetForm),
             ("Эксперимент", ExperimentForm), ("Запуск (run)", RunForm)]

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Внести данные")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Выберите, что добавить:"))
        for caption, form in self.FORMS:
            btn = QPushButton(caption)
            btn.setMinimumHeight(34)
            btn.clicked.connect(lambda _=False, f=form: self.open_form(f))
            layout.addWidget(btn)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        layout.addWidget(close)

    def open_form(self, form_cls):
        try:
            form = form_cls(self.db, self)
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        form.exec()


# Сводная таблица ЛР1
class ReportTab(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db

        self.attack = QComboBox()
        self.status = QComboBox()
        self.family = QComboBox()
        for combo, enum in ((self.attack, "attack_type"), (self.status, "run_status"), (self.family, "model_family")):
            combo.addItem("Все", None)
            for v in db.enum_values(enum):
                combo.addItem(v, v)
        self.use_from = QCheckBox("с")
        self.date_from = QDateEdit(QDate.currentDate().addMonths(-3))
        self.use_to = QCheckBox("по")
        self.date_to = QDateEdit(QDate.currentDate())
        for d in (self.date_from, self.date_to):
            d.setCalendarPopup(True)
            d.setDisplayFormat("yyyy-MM-dd")
        self.use_f1 = QCheckBox("F1 ≥")
        self.min_f1 = QDoubleSpinBox()
        self.min_f1.setRange(0, 1)
        self.min_f1.setSingleStep(0.05)
        self.min_f1.setDecimals(2)
        self.min_f1.setValue(0.9)

        apply_btn = QPushButton("Применить")
        apply_btn.clicked.connect(self.load)
        reset_btn = QPushButton("Сбросить")
        reset_btn.clicked.connect(self.reset)

        filters = QGroupBox("Фильтры")
        grid = QGridLayout(filters)
        grid.addWidget(QLabel("Тип атаки:"), 0, 0)
        grid.addWidget(self.attack, 0, 1)
        grid.addWidget(QLabel("Статус:"), 0, 2)
        grid.addWidget(self.status, 0, 3)
        grid.addWidget(QLabel("Семейство:"), 0, 4)
        grid.addWidget(self.family, 0, 5)
        grid.addWidget(QLabel("Дата запуска:"), 1, 0)
        dates = QHBoxLayout()
        for w in (self.use_from, self.date_from, self.use_to, self.date_to):
            dates.addWidget(w)
        grid.addLayout(dates, 1, 1, 1, 3)
        grid.addWidget(self.use_f1, 1, 4)
        grid.addWidget(self.min_f1, 1, 5)
        grid.addWidget(apply_btn, 0, 6)
        grid.addWidget(reset_btn, 1, 6)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.count = QLabel()
        layout = QVBoxLayout(self)
        layout.addWidget(filters)
        layout.addWidget(self.table)
        layout.addWidget(self.count)
        self.load()

    # Сброс фильтров
    def reset(self):
        for combo in (self.attack, self.status, self.family):
            combo.setCurrentIndex(0)
        for chk in (self.use_from, self.use_to, self.use_f1):
            chk.setChecked(False)
        self.load()

    # Загрузка данных
    def load(self):
        try:
            rows, cols = self.db.report(
                attack=self.attack.currentData(),
                status=self.status.currentData(),
                family=self.family.currentData(),
                date_from=self.date_from.date().toPython() if self.use_from.isChecked() else None,
                date_to=self.date_to.date().toPython() if self.use_to.isChecked() else None,
                min_f1=self.min_f1.value() if self.use_f1.isChecked() else None,
            )
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        self.table.setSortingEnabled(False)
        self.table.clear()
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, "" if value is None else (float(value) if hasattr(value, "as_tuple") else value))
                self.table.setItem(r, c, item)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSortingEnabled(True)
        self.count.setText(f"Найдено запусков: {len(rows)}")


# Окно вывода данных
class DataWindow(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Вывод данных")
        self.setModal(True)
        self.resize(1300, 760)
        tabs = QTabWidget()
        for title, cls in [("Сводная таблица", ReportTab), ("Конструктор SELECT (ROLLUP, CUBE, CASE)", SelectBuilderTab4),
                           ("Конструктор CTE (WITH)", CteBuilderTab),
                           ("Подзапросы (ANY / ALL / EXISTS)", SubqueryTab),
                           ("Поиск по тексту (LIKE / regex / SIMILAR TO)", SearchTab), ("Мастер JOIN", JoinWizardTab)]:
            try:
                tabs.addTab(cls(db, self), title)
            except DbError as e:
                tabs.addTab(QLabel(f"Вкладка недоступна: {e}"), title)
        strings = QPushButton("Строковые функции…")
        strings.clicked.connect(lambda: StringsDialog(db, self).exec())
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(strings)
        bottom.addStretch()
        bottom.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addLayout(bottom)


# Главное окно
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database()
        self.setWindowTitle("ЛР4 — ИИ для обнаружения DDoS-атак (PostgreSQL)")
        self.resize(760, 600)

        cfg = load_config()
        self.host = QLineEdit(cfg["host"])
        self.port = QLineEdit(cfg["port"])
        self.dbname = QLineEdit(cfg["dbname"])
        self.user = QLineEdit(cfg["user"])
        self.password = QLineEdit(cfg["password"])
        self.password.setEchoMode(QLineEdit.Password)
        self.connect_btn = QPushButton("Подключиться")
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.status = QLabel("Не подключено")

        conn_box = QGroupBox("Подключение к PostgreSQL")
        conn_form = QFormLayout(conn_box)
        conn_form.addRow("Хост:", self.host)
        conn_form.addRow("Порт:", self.port)
        conn_form.addRow("База данных:", self.dbname)
        conn_form.addRow("Пользователь:", self.user)
        conn_form.addRow("Пароль:", self.password)
        row = QHBoxLayout()
        row.addWidget(self.connect_btn)
        row.addWidget(self.status, 1)
        conn_form.addRow(row)

        self.actions = []
        actions_box = QGroupBox("Действия")
        grid = QGridLayout(actions_box)
        for i, (caption, handler) in enumerate([
            ("Создать схему и таблицы", self.create_schema),
            ("Внести данные", self.insert_data),
            ("Показать данные", self.show_data),
            ("Добавить демо-данные", self.seed_demo),
            ("Проверить ссылочную целостность", self.check_integrity),
            ("Изменить структуру (ALTER TABLE)", self.alter_structure),
            ("Пользовательские типы", self.user_types),
            ("Представления (VIEW / MATERIALIZED VIEW)", self.views),
        ]):
            btn = QPushButton(caption)
            btn.setMinimumHeight(38)
            btn.setEnabled(False)
            btn.clicked.connect(handler)
            grid.addWidget(btn, i // 2, i % 2)
            self.actions.append(btn)

        self.journal = QPlainTextEdit()
        self.journal.setReadOnly(True)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(conn_box)
        layout.addWidget(actions_box)
        layout.addWidget(QLabel("Журнал (полный лог — app.log):"))
        layout.addWidget(self.journal)
        self.setCentralWidget(central)

    # Запись в журнал
    def note(self, text):
        self.journal.appendPlainText(f"{datetime.now():%H:%M:%S}  {text}")

    # Подключение / отключение
    def toggle_connection(self):
        if self.db.connected:
            self.db.close()
            self.set_connected(False)
            self.note("Соединение закрыто")
            return
        try:
            self.db.connect(self.host.text().strip(), self.port.text().strip(), self.dbname.text().strip(),
                            self.user.text().strip(), self.password.text())
        except DbError as e:
            self.note("Ошибка подключения")
            show_error(self, "Ошибка подключения", str(e))
            return
        self.set_connected(True)
        self.note(f"Подключено к {self.dbname.text()} на {self.host.text()}:{self.port.text()}")

    def set_connected(self, ok):
        self.connect_btn.setText("Отключиться" if ok else "Подключиться")
        self.status.setText("Подключено" if ok else "Не подключено")
        for w in (self.host, self.port, self.dbname, self.user, self.password):
            w.setEnabled(not ok)
        for btn in self.actions:
            btn.setEnabled(ok)

    # Создание схемы
    def create_schema(self):
        answer = QMessageBox.question(self, "Создать схему",
                                      "Схема ddos_ai будет пересоздана, все данные в ней удалятся. Продолжить?")
        if answer != QMessageBox.Yes:
            return
        try:
            self.db.create_schema()
        except DbError as e:
            show_error(self, "Ошибка DDL", str(e))
            return
        self.note("Создана схема ddos_ai: 3 ENUM-типа, таблицы models, datasets, experiments, runs")
        QMessageBox.information(self, "Готово", "Схема, типы и таблицы созданы.")

    # Ввод данных
    def insert_data(self):
        InsertDialog(self.db, self).exec()
        self.note("Закрыто окно ввода данных")

    # Вывод данных
    def show_data(self):
        DataWindow(self.db, self).exec()

    # Представления
    def views(self):
        try:
            dialog = ViewsDialog(self.db, self)
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        dialog.exec()

    # Пользовательские типы
    def user_types(self):
        try:
            dialog = TypesDialog(self.db, self)
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        dialog.exec()

    # Изменение структуры
    def alter_structure(self):
        try:
            dialog = AlterDialog(self.db, self)
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        dialog.exec()

    # Демо-данные
    def seed_demo(self):
        try:
            self.db.seed_demo()
        except DbError as e:
            show_error(self, "Ошибка вставки — выполнен ROLLBACK", str(e))
            return
        self.note("Добавлены демо-данные: 4 модели, 3 датасета, 4 эксперимента, 8 запусков")
        QMessageBox.information(self, "Готово", "Демо-данные добавлены одной транзакцией.")

    # Проверка ссылочной целостности
    def check_integrity(self):
        try:
            results = self.db.integrity_check()
        except DbError as e:
            show_error(self, "Ошибка", str(e))
            return
        lines = []
        for name, allowed, text in results:
            mark = "✔ разрешено" if allowed else "✖ запрещено БД"
            lines.append(f"{mark} — {name}\n    {text}")
        self.note("Выполнена проверка ссылочной целостности (изменения отменены)")
        box = QMessageBox(self)
        box.setWindowTitle("Ссылочная целостность")
        box.setText("Результаты проверки (все изменения отменены через ROLLBACK):")
        box.setInformativeText("\n\n".join(lines))
        box.exec()

    def closeEvent(self, event):
        self.db.close()
        log.info("Приложение закрыто")
        super().closeEvent(event)


# Точка входа
def main():
    app = QApplication(sys.argv)
    log.info("Приложение запущено")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
