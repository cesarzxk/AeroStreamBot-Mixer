import importlib.util
import pathlib
import sys
import types
import unittest

# Minimal PyQt5 stubs so the module can be imported in a headless test environment.
qtwidgets = types.ModuleType("PyQt5.QtWidgets")
qtwidgets.QApplication = type("QApplication", (), {})
qtwidgets.QMainWindow = type("QMainWindow", (), {})
qtwidgets.QWidget = type("QWidget", (), {})
qtwidgets.QPushButton = type("QPushButton", (), {})
qtwidgets.QSlider = type("QSlider", (), {})
qtwidgets.QLabel = type("QLabel", (), {})
qtwidgets.QVBoxLayout = type("QVBoxLayout", (), {})
qtwidgets.QHBoxLayout = type("QHBoxLayout", (), {})
qtwidgets.QFrame = type("QFrame", (), {})
qtwidgets.QListWidget = type("QListWidget", (), {})
qtwidgets.QListWidgetItem = type("QListWidgetItem", (), {})
qtwidgets.QLineEdit = type("QLineEdit", (), {})
qtwidgets.QSizePolicy = type("QSizePolicy", (), {})
qtwidgets.QSystemTrayIcon = type("QSystemTrayIcon", (), {})
qtwidgets.QMenu = type("QMenu", (), {})
qtwidgets.QAction = type("QAction", (), {})
qtwidgets.QComboBox = type("QComboBox", (), {})

qtcore = types.ModuleType("PyQt5.QtCore")
qtcore.Qt = type("Qt", (), {"Horizontal": 1, "LeftButton": 1, "WA_TranslucentBackground": 1,
                 "FramelessWindowHint": 1, "WindowStaysOnTopHint": 1, "AlignCenter": 1, "NoPen": 0, "transparent": 0})
qtcore.QTimer = type("QTimer", (), {})

qtgui = types.ModuleType("PyQt5.QtGui")
qtgui.QColor = type("QColor", (), {})
qtgui.QPalette = type("QPalette", (), {})
qtgui.QIcon = type("QIcon", (), {})
qtgui.QPixmap = type("QPixmap", (), {})
qtgui.QPainter = type("QPainter", (), {})
qtgui.QBrush = type("QBrush", (), {})
qtgui.QPen = type("QPen", (), {})

pyqt5 = types.ModuleType("PyQt5")
pyqt5.QtWidgets = qtwidgets
pyqt5.QtCore = qtcore
pyqt5.QtGui = qtgui

sys.modules.setdefault("PyQt5", pyqt5)
sys.modules.setdefault("PyQt5.QtWidgets", qtwidgets)
sys.modules.setdefault("PyQt5.QtCore", qtcore)
sys.modules.setdefault("PyQt5.QtGui", qtgui)

MODULE_PATH = pathlib.Path(__file__).resolve(
).parents[1] / "stream-audio-mixer.py"
SPEC = importlib.util.spec_from_file_location(
    "stream_audio_mixer", MODULE_PATH)
stream_audio_mixer = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(stream_audio_mixer)


class TestInputMode(unittest.TestCase):
    def test_mic_mode_uses_default_source(self):
        self.assertEqual(
            stream_audio_mixer.resolve_loopback_source(
                "mic", "alsa_output.pci", "alsa_input.usb"),
            "alsa_input.usb",
        )

    def test_desktop_mode_uses_default_sink_monitor(self):
        self.assertEqual(
            stream_audio_mixer.resolve_loopback_source(
                "desktop", "alsa_output.pci", "alsa_input.usb"),
            "alsa_output.pci.monitor",
        )

    def test_desktop_plus_mic_mode_keeps_both_sources(self):
        self.assertEqual(
            stream_audio_mixer.resolve_loopback_source(
                "desktop", "alsa_output.pci", "alsa_input.usb"),
            "alsa_output.pci.monitor",
        )
        self.assertEqual(
            stream_audio_mixer.resolve_loopback_source(
                "mic", "alsa_output.pci", "alsa_input.usb"),
            "alsa_input.usb",
        )


if __name__ == "__main__":
    unittest.main()
