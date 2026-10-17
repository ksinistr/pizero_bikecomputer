import numpy as np

from modules.app_logger import app_logger
from .display_core import Display, MIP_DISPLAY_PARAMS

SHARP_DRM_DEFAULT_MONO_CUTOFF = 32
MONO_CUTOFF_STEP = 8
EMULATED_BUTTON_PROFILE = "Button_Shim"
LUMA_WEIGHTS = np.array([77, 150, 29], dtype=np.uint32)
BAYER_4X4 = np.array(
    [
        [0, 8, 2, 10],
        [12, 4, 14, 6],
        [3, 11, 1, 9],
        [15, 7, 13, 5],
    ],
    dtype=np.int32,
)

MONO_PANELS = tuple(
    name for name, params in MIP_DISPLAY_PARAMS.items() if not params["has_color"]
)


def mono_thresholds(height, width, cutoff, ordered_dither):
    if not ordered_dither:
        return np.full((height, width), cutoff, dtype=np.uint32)
    tile = np.clip(cutoff + BAYER_4X4 * 16 - 120, 1, 255).astype(np.uint32)
    reps = (height // 4 + 1, width // 4 + 1)
    return np.tile(tile, reps)[:height, :width]


def rgb_to_mono(rgb, cutoff, ordered_dither):
    luminance = rgb.astype(np.uint32) @ LUMA_WEIGHTS
    thresholds = mono_thresholds(*luminance.shape, cutoff, ordered_dither)
    return luminance >= (thresholds << 8)


class MipMonoEmulator(Display):
    send = True
    has_color = True
    color = 2

    def __init__(self, config, panel_name, scale):
        super().__init__(config)
        self.panel_name = panel_name
        self.size = MIP_DISPLAY_PARAMS[panel_name]["size"]
        self.scale = scale
        self.mono_cutoff = SHARP_DRM_DEFAULT_MONO_CUTOFF
        self.ordered_dither = False
        self.view = None
        self._rgb = None
        app_logger.info(f"emulating {panel_name}, scale={scale or 'auto'}")

    def start_coroutine(self):
        from modules.pyqt.pyqt_mip_emulator import attach_mip_emulator

        self.view = attach_mip_emulator(self.config.gui, self)
        self._render()

    def update(self, buf, direct_update):
        rgb = np.array(buf, dtype=np.uint8)
        if self._rgb is not None and np.array_equal(rgb, self._rgb):
            return
        self._rgb = rgb
        self._render()

    def _render(self):
        if self.view is None or self._rgb is None:
            return
        self.view.show_frame(
            rgb_to_mono(self._rgb, self.mono_cutoff, self.ordered_dither),
            self.conversion_label,
        )

    @property
    def conversion_label(self):
        dither = "bayer 4x4" if self.ordered_dither else "off"
        return f"mono_cutoff={self.mono_cutoff}  dither={dither}"

    def adjust_mono_cutoff(self, steps):
        self.mono_cutoff = int(
            np.clip(self.mono_cutoff + steps * MONO_CUTOFF_STEP, 0, 255)
        )
        self._render()

    def toggle_ordered_dither(self):
        self.ordered_dither = not self.ordered_dither
        self._render()

    def press_button(self, button, long_press):
        self.config.button_config.press_button(
            EMULATED_BUTTON_PROFILE, button, int(long_press)
        )
