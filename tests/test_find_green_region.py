#!/usr/bin/env python3
"""Тесты детекции зелёной кнопки на синтетических изображениях.

Запуск (без устройства и adb):   python -m unittest discover -s tests
"""

import os
import sys
import unittest

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import GreenRegion, find_green_region


def make_image(width: int, height: int, color=(255, 255, 255)) -> Image.Image:
    return Image.new("RGB", (width, height), color)


class FindGreenRegionTests(unittest.TestCase):
    def require_region(self, region: GreenRegion | None) -> GreenRegion:
        """Сужает тип до GreenRegion или валит тест (self.fail -> NoReturn)."""
        if region is None:
            self.fail("зелёная кнопка не найдена")
        return region

    def test_finds_green_button_and_center(self):
        img = make_image(400, 300)
        # Кнопка 100x40 в координатах x:[50,149], y:[100,139]
        ImageDraw.Draw(img).rectangle([50, 100, 149, 139], fill=(0, 200, 0))

        region = self.require_region(find_green_region(img))

        self.assertEqual(region.bbox[:2], (50, 100))
        self.assertEqual(region.bbox[2:], (100, 40))
        self.assertEqual((region.cx, region.cy), (99, 119))

    def test_returns_none_when_no_green(self):
        img = make_image(400, 300, color=(30, 30, 30))
        ImageDraw.Draw(img).rectangle([50, 100, 149, 139], fill=(220, 40, 40))

        self.assertIsNone(find_green_region(img))

    def test_ignores_tiny_green_noise(self):
        img = make_image(400, 300)
        draw = ImageDraw.Draw(img)
        draw.rectangle([10, 10, 14, 14], fill=(0, 255, 0))     # 5x5 = 25 px, ниже порога
        draw.rectangle([50, 100, 349, 159], fill=(0, 255, 0))  # крупная кнопка

        region = self.require_region(find_green_region(img))

        self.assertGreater(region.area, 25)
        self.assertEqual(region.cx, 199)  # центр крупной кнопки

    def test_picks_largest_of_several_green_regions(self):
        img = make_image(400, 300)
        draw = ImageDraw.Draw(img)
        draw.rectangle([10, 10, 59, 39], fill=(0, 255, 0))      # 50x30
        draw.rectangle([100, 100, 349, 199], fill=(0, 255, 0))  # 250x100 (крупнее)

        region = self.require_region(find_green_region(img))

        self.assertEqual((region.cx, region.cy), (224, 149))

    def test_blue_button_is_not_green(self):
        img = make_image(400, 300)
        ImageDraw.Draw(img).rectangle([50, 100, 349, 199], fill=(0, 100, 255))

        self.assertIsNone(find_green_region(img))


if __name__ == "__main__":
    unittest.main()
