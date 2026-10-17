import math
import os
from datetime import datetime

import numpy as np

from modules.app_logger import app_logger
from modules.qt._qt_qtwidgets import QtCore, QtGui, QtWidgets

LCD_WHITE = (200, 202, 194)
LCD_BLACK = (28, 30, 33)
PURE_WHITE = (255, 255, 255)
PURE_BLACK = (0, 0, 0)

Key = QtCore.Qt.Key
BUTTON_KEYS = {
    Key.Key_A: "A",
    Key.Key_B: "B",
    Key.Key_C: "C",
    Key.Key_D: "D",
    Key.Key_E: "E",
}
HELP_TEXT = (
    "A-E: buttons (Shift = long press)   [ ]: mono_cutoff   \\: dither   P: save PNG"
)


def mono_to_rgb(mono, white, black):
    return np.where(mono[..., None], white, black).astype(np.uint8)


def rgb_to_qimage(rgb):
    height, width, _ = rgb.shape
    return QtGui.QImage(
        rgb.tobytes(), width, height, width * 3, QtGui.QImage.Format.Format_RGB888
    ).copy()


class MipEmulatorCanvas(QtWidgets.QWidget):
    def __init__(self, size, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self.panel_size = size
        self.preferred_scale = 1
        self.image = None

    def logical_size(self, scale):
        ratio = self.devicePixelRatioF()
        return QtCore.QSize(
            math.ceil(self.panel_size[0] * scale / ratio),
            math.ceil(self.panel_size[1] * scale / ratio),
        )

    def sizeHint(self):
        return self.logical_size(self.preferred_scale)

    def minimumSizeHint(self):
        return self.logical_size(1)

    def set_preferred_scale(self, scale):
        self.preferred_scale = scale
        self.updateGeometry()

    @property
    def scale(self):
        ratio = self.devicePixelRatioF()
        fit = min(
            self.width() * ratio / self.panel_size[0],
            self.height() * ratio / self.panel_size[1],
        )
        return max(1, int(fit))

    def image_rect(self):
        ratio = self.devicePixelRatioF()
        width = self.panel_size[0] * self.scale
        height = self.panel_size[1] * self.scale
        left = (round(self.width() * ratio) - width) // 2
        top = (round(self.height() * ratio) - height) // 2
        return QtCore.QRectF(
            left / ratio, top / ratio, width / ratio, height / ratio
        )

    def set_image(self, image):
        self.image = image
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        if self.image is None:
            painter.fillRect(self.image_rect(), QtGui.QColor(*LCD_WHITE))
        else:
            painter.drawImage(self.image_rect(), self.image)
        painter.end()


class MipEmulatorPanel(QtWidgets.QWidget):
    def __init__(self, size, parent=None):
        super().__init__(parent)
        self.mono = None
        self.caption = ""
        self.canvas = MipEmulatorCanvas(size, self)
        self.status = QtWidgets.QLabel(self)
        help_label = QtWidgets.QLabel(HELP_TEXT, self)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.status)
        layout.addWidget(help_label)

    def show_frame(self, mono, caption):
        self.mono = mono
        self.caption = caption
        self.canvas.set_image(rgb_to_qimage(mono_to_rgb(mono, LCD_WHITE, LCD_BLACK)))
        self.update_status()

    def update_status(self):
        self.status.setText(f"{self.caption}  scale=x{self.canvas.scale} (screen pixels)")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_status()

    def save(self, directory):
        if self.mono is None:
            return
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        exact = rgb_to_qimage(mono_to_rgb(self.mono, PURE_WHITE, PURE_BLACK))
        exact_path = os.path.join(directory, f"{stamp}_mono.png")
        lcd_path = os.path.join(directory, f"{stamp}_lcd.png")
        exact.save(exact_path)
        scale = self.canvas.scale
        self.canvas.image.scaled(
            self.mono.shape[1] * scale, self.mono.shape[0] * scale
        ).save(lcd_path)
        app_logger.info(f"emulator frame: {exact_path}, {lcd_path}")


class MipEmulatorKeys(QtCore.QObject):
    def __init__(self, emulator, panel, screenshot_dir, parent=None):
        super().__init__(parent)
        self.emulator = emulator
        self.panel = panel
        self.screenshot_dir = screenshot_dir

    def eventFilter(self, obj, event):
        if event.type() != QtCore.QEvent.Type.KeyPress or event.isAutoRepeat():
            return False
        if isinstance(QtWidgets.QApplication.focusWidget(), QtWidgets.QLineEdit):
            return False

        key = event.key()
        if key in BUTTON_KEYS:
            shift = QtCore.Qt.KeyboardModifier.ShiftModifier
            self.emulator.press_button(BUTTON_KEYS[key], bool(event.modifiers() & shift))
        elif key == Key.Key_BracketLeft:
            self.emulator.adjust_mono_cutoff(-1)
        elif key == Key.Key_BracketRight:
            self.emulator.adjust_mono_cutoff(1)
        elif key == Key.Key_Backslash:
            self.emulator.toggle_ordered_dither()
        elif key == Key.Key_P:
            self.panel.save(self.screenshot_dir)
        else:
            return False
        return True


WINDOW_FRAME_ALLOWANCE = QtCore.QSize(16, 48)


def largest_fitting_scale(panel_size, room, ratio):
    return max(
        1,
        int(
            min(
                room.width() * ratio / panel_size[0],
                room.height() * ratio / panel_size[1],
            )
        ),
    )


def fit_to_screen(window, canvas, requested_scale):
    available = window.screen().availableGeometry().size()
    chrome = window.minimumSizeHint() - canvas.minimumSizeHint()
    room = available - chrome - WINDOW_FRAME_ALLOWANCE
    scale = requested_scale or largest_fitting_scale(
        canvas.panel_size, room, canvas.devicePixelRatioF()
    )
    canvas.set_preferred_scale(scale)
    target = (chrome + canvas.sizeHint()).boundedTo(available - WINDOW_FRAME_ALLOWANCE)

    window.hide()
    window.setMinimumSize(window.minimumSizeHint())
    window.resize(target)
    window.show()


def attach_mip_emulator(gui, emulator):
    panel = MipEmulatorPanel(emulator.size)
    dock = QtWidgets.QDockWidget(f"{emulator.panel_name} (emulated)", gui.main_window)
    dock.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
    dock.setWidget(panel)

    gui.root_widget.setFixedSize(*emulator.size)
    gui.main_window.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, dock)
    QtCore.QTimer.singleShot(
        0, lambda: fit_to_screen(gui.main_window, panel.canvas, emulator.scale)
    )

    keys = MipEmulatorKeys(emulator, panel, gui.config.G_SCREENSHOT_DIR, gui.main_window)
    gui.app.installEventFilter(keys)
    return panel
