import sys
import os
import re
import cv2
import pytesseract
import sqlite3
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QLabel, QPushButton, 
                            QVBoxLayout, QWidget, QFileDialog, QMessageBox,
                            QHBoxLayout, QLineEdit, QGroupBox, QTableWidget,
                            QTableWidgetItem, QHeaderView)
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtCore import Qt

# Настройки для Windows
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'  # Путь к tesseract
os.environ['TESSDATA_PREFIX'] = r'C:\Program Files\Tesseract-OCR\tessdata'  # Путь к данным

class LicensePlateRecognizer:
    #для российских номеров ГОСТ
    PLATE_PATTERNS = [
        re.compile(r'^[АВЕКМНОРСТУХ]{1}\d{3}[АВЕКМНОРСТУХ]{2}\d{2,3}$'),
        re.compile(r'^[АВЕКМНОРСТУХ]{2}\d{3}\d{2,3}$'),
        re.compile(r'^[АВЕКМНОРСТУХ]{2}\d{4}\d{2,3}$'),
        re.compile(r'^[АВЕКМНОРСТУХ]{1}\d{3}\d{2,3}$')
    ]
    
    #похожие символы
    CHAR_REPLACEMENTS = {
        'B': 'В', 'C': 'С', 'E': 'Е', 'K': 'К', 'M': 'М',
        'H': 'Н', 'O': 'О', 'P': 'Р', 'T': 'Т', 'X': 'Х',
        'Y': 'У', 'A': 'А', '0': 'О', '3': 'З', '4': 'А'
    }

    def __init__(self):
        #путь к каскаду для винды
        cascade_path = os.path.dirname(cv2.__file__) + r'\data\haarcascade_russian_plate_number.xml'
        if not os.path.exists(cascade_path):
            QMessageBox.critical(None, "Ошибка", "Не найден файл haarcascade_russian_plate_number.xml")
            sys.exit(1)
        self.plate_cascade = cv2.CascadeClassifier(cascade_path)

    def preprocess_image(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.bilateralFilter(gray, 11, 17, 17)
        gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        return gray

    def correct_plate_number(self, text):
        return ''.join([self.CHAR_REPLACEMENTS.get(char, char) for char in text.upper()])

    def validate_plate_number(self, text):
        text = self.correct_plate_number(text)
        return any(pattern.match(text) for pattern in self.PLATE_PATTERNS)

    def detect_plates(self, image_path):
        try:
            img = cv2.imread(image_path)
            if img is None:
                return None, None, None

            gray = self.preprocess_image(img)
            plates = self.plate_cascade.detectMultiScale(gray, 1.1, 5)

            if len(plates) == 0:
                return None, None, None

            x, y, w, h = plates[0]
            plate_img = gray[y:y+h, x:x+w]
            
            #улучшение изображения
            plate_img = cv2.equalizeHist(plate_img)
            plate_img = cv2.GaussianBlur(plate_img, (3, 3), 0)

            #распознавание текста
            custom_config = r'--oem 3 --psm 6 -l rus+eng'
            text = pytesseract.image_to_string(plate_img, config=custom_config)
            text = ''.join(e for e in text if e.isalnum()).upper()
            text = self.correct_plate_number(text)
            
            if not self.validate_plate_number(text):
                return None, None, None

            #визуализация
            cv2.rectangle(img, (x, y), (x+w, y+h), (0, 255, 0), 2)
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            q_img = QImage(img_rgb.data, img_rgb.shape[1], img_rgb.shape[0], 
                         img_rgb.shape[1]*3, QImage.Format_RGB888)

            return q_img, text, (x, y, w, h)

        except Exception as e:
            print(f"Ошибка: {e}")
            return None, None, None

class DatabaseManager:
    def __init__(self, db_name='parking.db'):
        self.conn = sqlite3.connect(db_name)
        self.create_tables()
    
    def create_tables(self):
        with self.conn:
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                plate TEXT UNIQUE NOT NULL,
                reg_date TEXT NOT NULL
            )''')
            
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS parking_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                exit_time TEXT,
                FOREIGN KEY (plate) REFERENCES users(plate)
            )''')
    
    def add_user(self, name, phone, plate):
        try:
            with self.conn:
                self.conn.execute('''
                INSERT INTO users (name, phone, plate, reg_date)
                VALUES (?, ?, ?, ?)''', 
                (name, phone, plate, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            return True
        except sqlite3.IntegrityError:
            return False
    
    def check_user(self, plate):
        with self.conn:
            cursor = self.conn.execute('SELECT name, phone FROM users WHERE plate = ?', (plate,))
            return cursor.fetchone()
    
    def log_entry(self, plate):
        if not self.check_user(plate):
            return False
        
        with self.conn:
            self.conn.execute('''
            INSERT INTO parking_log (plate, entry_time)
            VALUES (?, ?)''', 
            (plate, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        return True
    
    def log_exit(self, plate):
        with self.conn:
            self.conn.execute('''
            UPDATE parking_log SET exit_time = ?
            WHERE plate = ? AND exit_time IS NULL''',
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), plate))
        return True
    
    def get_users(self):
        with self.conn:
            cursor = self.conn.execute('SELECT name, phone, plate, reg_date FROM users')
            return cursor.fetchall()

class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Парковочная система")
        self.setGeometry(100, 100, 900, 600)
        self.db = DatabaseManager()
        self.init_ui()
    
    def init_ui(self):
        main_widget = QWidget()
        layout = QHBoxLayout()
        
        #левая панелька
        left_panel = QVBoxLayout()
        
        #блок изображения
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(640, 480)
        self.image_label.setStyleSheet("border: 1px solid #ccc;")
        
        #информация
        self.plate_label = QLabel("Номер: не распознан")
        self.plate_label.setStyleSheet("font-size: 16px;")
        
        self.status_label = QLabel("Статус: ожидание")
        self.user_label = QLabel("Владелец: неизвестен")
        
        #кнопки
        btn_load = QPushButton("Загрузить фото")
        btn_load.clicked.connect(self.load_image)
        
        btn_process = QPushButton("Распознать номер")
        btn_process.clicked.connect(self.process_image)
        
        btn_entry = QPushButton("Разрешить въезд")
        btn_entry.clicked.connect(self.allow_entry)
        btn_entry.setEnabled(False)
        
        btn_exit = QPushButton("Зафиксировать выезд")
        btn_exit.clicked.connect(self.record_exit)
        btn_exit.setEnabled(False)
        
        left_panel.addWidget(self.image_label)
        left_panel.addWidget(self.plate_label)
        left_panel.addWidget(self.status_label)
        left_panel.addWidget(self.user_label)
        left_panel.addWidget(btn_load)
        left_panel.addWidget(btn_process)
        left_panel.addWidget(btn_entry)
        left_panel.addWidget(btn_exit)
        
        #правая панелька
        right_panel = QVBoxLayout()
        
        #форма добавления
        add_form = QGroupBox("Регистрация авто")
        form_layout = QVBoxLayout()
        
        self.input_name = QLineEdit(placeholderText="ФИО владельца")
        self.input_phone = QLineEdit(placeholderText="Телефон")
        self.input_plate = QLineEdit(placeholderText="Госномер")
        
        btn_add = QPushButton("Добавить")
        btn_add.clicked.connect(self.add_user)
        
        form_layout.addWidget(self.input_name)
        form_layout.addWidget(self.input_phone)
        form_layout.addWidget(self.input_plate)
        form_layout.addWidget(btn_add)
        add_form.setLayout(form_layout)
        
        #таблица пользователей
        self.users_table = QTableWidget()
        self.users_table.setColumnCount(4)
        self.users_table.setHorizontalHeaderLabels(["ФИО", "Телефон", "Номер", "Дата регистрации"])
        self.users_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        
        btn_refresh = QPushButton("Обновить список")
        btn_refresh.clicked.connect(self.update_users_table)
        
        right_panel.addWidget(add_form)
        right_panel.addWidget(btn_refresh)
        right_panel.addWidget(self.users_table)
        
        layout.addLayout(left_panel, 60)
        layout.addLayout(right_panel, 40)
        main_widget.setLayout(layout)
        self.setCentralWidget(main_widget)
        
        self.update_users_table()
    
    def load_image(self):
        file, _ = QFileDialog.getOpenFileName(self, "Выберите фото", "", "Images (*.jpg *.png)")
        if file:
            self.current_image = file
            pixmap = QPixmap(file)
            self.image_label.setPixmap(pixmap.scaled(
                self.image_label.width(), self.image_label.height(), Qt.KeepAspectRatio))
            self.plate_label.setText("Номер: не распознан")
            self.status_label.setText("Статус: ожидание")
            self.user_label.setText("Владелец: неизвестен")
    
    def process_image(self):
        if not hasattr(self, 'current_image'):
            QMessageBox.warning(self, "Ошибка", "Сначала загрузите изображение!")
            return
        
        recognizer = LicensePlateRecognizer()
        img, plate, _ = recognizer.detect_plates(self.current_image)
        
        if img is None:
            QMessageBox.warning(self, "Ошибка", "Не удалось распознать номер!")
            return
        
        self.image_label.setPixmap(QPixmap.fromImage(img).scaled(
            self.image_label.width(), self.image_label.height(), Qt.KeepAspectRatio))
        
        if plate:
            self.current_plate = plate
            self.plate_label.setText(f"Номер: {plate}")
            user = self.db.check_user(plate)
            
            if user:
                name, phone = user
                self.status_label.setText("Статус: зарегистрирован")
                self.user_label.setText(f"Владелец: {name}\nТелефон: {phone}")
                self.findChild(QPushButton, "Разрешить въезд").setEnabled(True)
            else:
                self.status_label.setText("Статус: не зарегистрирован")
                QMessageBox.warning(self, "Внимание", "Автомобиль не зарегистрирован!")
    
    def allow_entry(self):
        if self.db.log_entry(self.current_plate):
            QMessageBox.information(self, "Успех", "Въезд разрешен. Шлагбаум открыт.")
            self.status_label.setText("Статус: на территории")
        else:
            QMessageBox.warning(self, "Ошибка", "Не удалось зарегистрировать въезд!")
    
    def record_exit(self):
        if self.db.log_exit(self.current_plate):
            QMessageBox.information(self, "Успех", "Выезд зафиксирован. Шлагбаум закрыт.")
            self.status_label.setText("Статус: выехал")
        else:
            QMessageBox.warning(self, "Ошибка", "Не удалось зафиксировать выезд!")
    
    def add_user(self):
        name = self.input_name.text().strip()
        phone = self.input_phone.text().strip()
        plate = self.input_plate.text().strip().upper()
        
        if not all([name, phone, plate]):
            QMessageBox.warning(self, "Ошибка", "Все поля должны быть заполнены!")
            return
        
        if self.db.add_user(name, phone, plate):
            QMessageBox.information(self, "Успех", "Автомобиль зарегистрирован!")
            self.input_name.clear()
            self.input_phone.clear()
            self.input_plate.clear()
            self.update_users_table()
        else:
            QMessageBox.warning(self, "Ошибка", "Этот номер уже зарегистрирован!")
    
    def update_users_table(self):
        users = self.db.get_users()
        self.users_table.setRowCount(len(users))
        
        for row, user in enumerate(users):
            for col, data in enumerate(user):
                item = QTableWidgetItem(str(data))
                item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                self.users_table.setItem(row, col, item)

if __name__ == "__main__":
    #проверка Tesseract
    try:
        pytesseract.get_tesseract_version()
    except:
        QMessageBox.critical(None, "Ошибка", 
            "Tesseract OCR не установлен или путь указан неверно!\n"
            "Скачайте и установите Tesseract с https://github.com/UB-Mannheim/tesseract/wiki\n"
            "Убедитесь, что в настройках указан правильный путь к tesseract.exe")
        sys.exit(1)
    
    app = QApplication(sys.argv)
    window = MainApp()
    window.show()
    sys.exit(app.exec_())
