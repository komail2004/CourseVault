"""CourseVault desktop UI."""
from pathlib import Path
from PySide6.QtCore import Qt, QObject, Signal, QThread
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
 QPushButton, QListWidget, QFileDialog, QMessageBox, QProgressBar, QFrame)
from .canvas import CanvasClient
from .export import export_course, safe_name

class Worker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    def __init__(self, task):
        super().__init__()
        self.task = task
    def run(self):
        try: self.finished.emit(self.task())
        except Exception as exc: self.failed.emit(str(exc))

class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.client = None
        self.courses = []
        self.threads = []
        self.setWindowTitle("CourseVault — Your learning, preserved")
        self.resize(980,680)
        self.setStyleSheet("""
            QWidget {background:#10131b;color:#e9ecf5;font-family:'Arial';font-size:14px}
            QLabel#heading {font-size:34px;font-weight:700;color:#fff}
            QLabel#muted {color:#a0a9bd}
            QPushButton {background:#7568f7;color:white;border:0;border-radius:12px;padding:13px 18px;font-weight:600}
            QPushButton:hover {background:#8a7eff}
            QPushButton:disabled {background:#373c50;color:#9298a7}
            QListWidget {background:#1a1e2a;border:1px solid #30364a;border-radius:16px;padding:12px;outline:none}
            QListWidget::item {padding:17px;border-radius:9px}
            QListWidget::item:selected {background:#34305d}
            QProgressBar {border:0;background:#30364a;border-radius:6px;height:12px}
            QProgressBar::chunk {background:#8a7eff;border-radius:6px}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48,40,48,40)
        layout.setSpacing(18)
        brand = QLabel("✦  COURSEVAULT")
        brand.setStyleSheet("font-size:13px;font-weight:700;color:#aaa3ff;letter-spacing:2px")
        layout.addWidget(brand)
        heading = QLabel("Your courses, beautifully preserved.")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        subtitle = QLabel("Connect to Canvas, select a course, and export the available materials into one ZIP.")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)
        actions = QHBoxLayout()
        self.connect_button = QPushButton("Connect to Bauman Canvas")
        self.connect_button.clicked.connect(self.connect)
        actions.addWidget(self.connect_button)
        self.export_button = QPushButton("Export selected course")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export)
        actions.addWidget(self.export_button)
        layout.addLayout(actions)
        layout.addWidget(QLabel("YOUR COURSES"))
        self.course_list = QListWidget()
        self.course_list.itemSelectionChanged.connect(lambda: self.export_button.setEnabled(bool(self.course_list.selectedItems())))
        layout.addWidget(self.course_list)
        self.progress = QProgressBar()
        self.progress.setRange(0,100)
        layout.addWidget(self.progress)
        self.status = QLabel("Ready to connect. Sign in using the official Canvas browser window.")
        self.status.setObjectName("muted")
        layout.addWidget(self.status)

    def background(self, task, callback):
        thread = QThread(self)
        worker = Worker(task)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(callback)
        worker.failed.connect(self.error)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self.threads.append(thread)
        thread.finished.connect(lambda: self.threads.remove(thread))
        thread.start()

    def error(self, message):
        self.status.setText("Error: "+message)
        QMessageBox.warning(self,"CourseVault",message)
        self.connect_button.setEnabled(True)
        self.export_button.setEnabled(bool(self.course_list.selectedItems()))

    def connect(self):
        self.connect_button.setEnabled(False)
        self.status.setText("Opening Canvas sign-in browser…")
        def task():
            client = CanvasClient(Path.home()/".coursevault"/"browser")
            client.open()
            client.wait_for_login()
            return client,client.courses()
        self.background(task,self.connected)

    def connected(self, result):
        self.client,self.courses = result
        self.course_list.clear()
        for course in self.courses: self.course_list.addItem(course.get("name") or "Untitled course")
        self.status.setText(f"Connected — {len(self.courses)} courses found.")
        self.connect_button.setEnabled(True)

    def export(self):
        row = self.course_list.currentRow()
        if row < 0 or not self.client: return
        course = self.courses[row]
        default = safe_name(course.get("name"))+".zip"
        filename,_ = QFileDialog.getSaveFileName(self,"Save course archive",str(Path.home()/"Downloads"/default),"ZIP archives (*.zip)")
        if not filename: return
        self.export_button.setEnabled(False)
        self.progress.setRange(0,0)
        self.status.setText("Scanning and exporting course…")
        self.background(lambda: export_course(self.client,course,Path(filename)),lambda report: self.exported(filename,report))

    def exported(self,filename,report):
        self.progress.setRange(0,100)
        self.progress.setValue(100)
        self.export_button.setEnabled(True)
        self.status.setText(f"Archive saved: {filename} — {len(report['downloaded'])} files; {len(report['skipped'])} skipped.")
        QMessageBox.information(self,"Export complete",self.status.text())

    def closeEvent(self,event):
        # Browser profile is local and may retain a Canvas session.
        # Browser lifetime is managed by Playwright; never capture user passwords.
        event.accept()

def main():
    app = QApplication([])
    window = Window()
    window.show()
    app.exec()

if __name__ == "__main__":
    main()
