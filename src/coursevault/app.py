"""Cross-platform Qt desktop interface for CourseVault."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from .backend import DEFAULT_ORIGIN, Cancelled, Session, safe_name


class Worker(QObject):
    result = Signal(object)
    error = Signal(str)
    status = Signal(str)
    finished = Signal()

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    def run(self):
        try:
            self.result.emit(self.operation(self.status.emit))
        except Cancelled:
            self.error.emit("Export cancelled; no incomplete archive was retained.")
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class CourseVault(QWidget):
    def __init__(self):
        super().__init__()
        self.courses = []
        self.jobs = []
        self.cancel = threading.Event()
        self.setWindowTitle("CourseVault · Your courses, preserved")
        self.resize(950, 700)
        self.setMinimumSize(640, 530)
        self.setStyleSheet("""
            QWidget {background:#10131c;color:#f0f1fa;font-family:Arial;font-size:14px}
            QLabel#brand {color:#aaa0ff;font-weight:bold;font-size:14px}
            QLabel#title {font-size:31px;font-weight:700;color:#fff}
            QLabel#muted {color:#a3acc1}
            QLabel#section {font-size:12px;color:#a3acc1;font-weight:700}
            QLineEdit {background:#1c2230;border:1px solid #3a4055;border-radius:12px;padding:14px;color:#f6f7ff}
            QPushButton {background:#7769f7;border:none;border-radius:12px;padding:14px 19px;font-weight:700}
            QPushButton:hover {background:#8b7fff}
            QPushButton:disabled {background:#33384a;color:#858c9c}
            QPushButton#secondary {background:#272d3f}
            QListWidget {background:#1b2030;border:1px solid #343a4e;border-radius:15px;padding:10px;outline:none}
            QListWidget::item {padding:15px;border-radius:9px}
            QListWidget::item:selected {background:#403b76}
            QProgressBar {border:0;background:#33384a;border-radius:5px;height:10px}
            QProgressBar::chunk {background:#a89dff;border-radius:5px}
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(44, 38, 44, 32)
        root.setSpacing(16)
        brand = QLabel("✦  C O U R S E V A U L T")
        brand.setObjectName("brand")
        root.addWidget(brand)
        heading = QLabel("Your learning, beautifully preserved.")
        heading.setObjectName("title")
        heading.setWordWrap(True)
        root.addWidget(heading)
        subtitle = QLabel("Securely connect to Canvas, choose a course, and save the available materials.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)
        root.addSpacing(8)
        root.addWidget(QLabel("CANVAS SERVER"))
        self.origin = QLineEdit(DEFAULT_ORIGIN)
        self.origin.setPlaceholderText("https://your-school.instructure.com")
        root.addWidget(self.origin)
        actions = QHBoxLayout()
        self.login_btn = QPushButton("Connect to Canvas")
        self.login_btn.clicked.connect(self.login)
        actions.addWidget(self.login_btn)
        self.refresh_btn = QPushButton("Refresh courses")
        self.refresh_btn.setObjectName("secondary")
        self.refresh_btn.clicked.connect(self.refresh)
        actions.addWidget(self.refresh_btn)
        root.addLayout(actions)
        section = QLabel("YOUR COURSES")
        section.setObjectName("section")
        root.addWidget(section)
        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self.selection_changed)
        root.addWidget(self.list, 1)
        bottom = QHBoxLayout()
        self.export_btn = QPushButton("Export selected course")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.export)
        bottom.addWidget(self.export_btn, 1)
        self.cancel_btn = QPushButton("Cancel export")
        self.cancel_btn.setObjectName("secondary")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel.set)
        bottom.addWidget(self.cancel_btn)
        root.addLayout(bottom)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        root.addWidget(self.progress)
        self.message = QLabel("Ready. Sign in through the official Canvas browser window.")
        self.message.setObjectName("muted")
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        self.refresh_btn.setEnabled(False)

    def selection_changed(self):
        self.export_btn.setEnabled(bool(self.list.selectedItems()) and not self.jobs)

    def run_job(self, operation, callback, exporting=False):
        self.login_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.origin.setEnabled(False)
        self.cancel_btn.setEnabled(exporting)
        self.progress.setRange(0, 0)
        thread = QThread(self)
        worker = Worker(operation)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.status.connect(self.message.setText)
        worker.result.connect(callback)
        worker.error.connect(self.show_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self.jobs.append(thread)
        def done():
            self.jobs.remove(thread)
            self.progress.setRange(0, 100)
            self.progress.setValue(100 if exporting else 0)
            self.login_btn.setEnabled(True)
            self.refresh_btn.setEnabled(True)
            self.origin.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.selection_changed()
        thread.finished.connect(done)
        thread.start()

    def session(self):
        return Session(origin=self.origin.text().strip())

    def login(self):
        server = self.origin.text().strip()
        self.message.setText("Opening the official Canvas sign-in page…")
        self.run_job(lambda emit: Session(origin=server).login(), self.logged_in)

    def logged_in(self, _):
        self.message.setText("Signed in. Loading your courses…")
        self.refresh()

    def refresh(self):
        server = self.origin.text().strip()
        self.message.setText("Loading courses…")
        self.run_job(lambda emit: Session(origin=server).courses(), self.loaded)

    def loaded(self, courses):
        self.courses = courses
        self.list.clear()
        for course in courses:
            self.list.addItem(course.get("name") or "Untitled course")
        self.message.setText(f"{len(courses)} active courses found. Select one to export.")

    def export(self):
        row = self.list.currentRow()
        if row < 0: return
        course = self.courses[row]
        suggested = str(Path.home() / "Downloads" / (safe_name(course.get("name")) + ".zip"))
        path, _ = QFileDialog.getSaveFileName(self, "Save Canvas course", suggested, "ZIP archive (*.zip)")
        if not path: return
        if not path.lower().endswith(".zip"): path += ".zip"
        self.cancel.clear()
        server = self.origin.text().strip()
        self.message.setText("Discovering course content…")
        self.run_job(
            lambda emit: Session(origin=server).export(course, Path(path), notify=emit, cancel=self.cancel),
            lambda report: self.exported(path, report),
            exporting=True,
        )

    def exported(self, path, report):
        count = len(report["downloaded"])
        skipped = len(report["skipped"])
        self.message.setText(f"Saved {path} — {count} files downloaded; {skipped} items skipped.")
        QMessageBox.information(self, "Archive saved", self.message.text())

    def show_error(self, message):
        self.message.setText(message)
        QMessageBox.warning(self, "CourseVault", message)

    def closeEvent(self, event):
        if self.jobs:
            event.ignore()
            QMessageBox.information(self, "CourseVault", "Please wait for the current operation to finish, or cancel the export.")
        else:
            event.accept()


def main():
    app = QApplication([])
    window = CourseVault()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
