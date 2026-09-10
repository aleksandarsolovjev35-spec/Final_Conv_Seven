from vision.overlay.palette import COLOR_OMISSION_LONG
from vision.overlay.renderers.omission_boundary import draw_omission_item


class LongOmissionRenderer:
    @staticmethod
    def draw_item(img, drawing):
        draw_omission_item(img, drawing, COLOR_OMISSION_LONG)
