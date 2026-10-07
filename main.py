#!/usr/bin/env python3

"""Запускает Android-приложение по имени пакета, находит зелёную кнопку и нажимает её.

Требуется: Python 3.12, adb в PATH, подключённое устройство.
Без Appium/UiAutomator — только скриншот + обработка изображения + input tap.
"""

import argparse
import io
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass

import numpy as np
from PIL import Image

# Диапазон «зелёного» в HSV (модель Pillow: H/S/V в [0, 255]).
GREEN_H_MIN = 40   # ~56°
GREEN_H_MAX = 115  # ~162°
GREEN_S_MIN = 40
GREEN_V_MIN = 60

# Минимальная площадь зелёной области в долях экрана, чтобы считать её кнопкой.
MIN_AREA_FRACTION = 0.001  # 0.1% экрана

# Допустимый диапазон пропорций bounding box (width/height) для «кнопки».
MIN_ASPECT, MAX_ASPECT = 0.1, 8.0


@dataclass
class GreenRegion:
    cx: int
    cy: int
    area: int
    bbox: tuple  # (x, y, w, h)


class ADB:
    def __init__(self, adb_path: str = "adb", serial: str | None = None):
        self.adb = adb_path
        self.serial = serial

    def _cmd(self, *args: str) -> list[str]:
        cmd = [self.adb]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        return cmd

    def run(self, *args: str, check: bool = True, timeout: float = 10.0):
        return subprocess.run(
            self._cmd(*args), capture_output=True, check=check, timeout=timeout
        )

    def is_installed(self, package: str) -> bool:
        proc = self.run("shell", "pm", "list", "packages", package, check=False)
        return f"package:{package}" in proc.stdout.decode(errors="replace")

    def launch_app(self, package: str) -> None:
        self.run(
            "shell", "monkey", "-p", package,
            "-c", "android.intent.category.LAUNCHER", "1",
        )

    def screenshot(self) -> Image.Image:
        proc = self.run("exec-out", "screencap", "-p")
        return Image.open(io.BytesIO(proc.stdout)).convert("RGB")

    def tap(self, x: int, y: int) -> None:
        self.run("shell", "input", "tap", str(int(x)), str(int(y)))


def find_green_region(img: Image.Image) -> GreenRegion | None:
    """Возвращает самую крупную зелёную область, похожую на кнопку, или None."""
    hsv = np.asarray(img.convert("HSV"))
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    mask = (h >= GREEN_H_MIN) & (h <= GREEN_H_MAX) \
        & (s >= GREEN_S_MIN) & (v >= GREEN_V_MIN)

    height, width = mask.shape
    min_area = int(width * height * MIN_AREA_FRACTION)

    coords = np.argwhere(mask)  # (N, 2) строки вида [y, x]
    if coords.size == 0:
        return None

    visited = np.zeros(mask.shape, dtype=bool)
    best: GreenRegion | None = None

    for y, x in coords:
        if visited[y, x]:
            continue

        # BFS по 4-связной компоненте (обходим только зелёные пиксели).
        visited[y, x] = True
        queue = deque([(y, x)])
        pts = []
        while queue:
            cy, cx = queue.popleft()
            pts.append((cy, cx))
            for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < height and 0 <= nx < width \
                        and mask[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True
                    queue.append((ny, nx))

        area = len(pts)
        if area < min_area:
            continue

        ys = [p[0] for p in pts]
        xs = [p[1] for p in pts]
        miny, maxy = min(ys), max(ys)
        minx, maxx = min(xs), max(xs)
        bw, bh = maxx - minx + 1, maxy - miny + 1

        aspect = bw / max(bh, 1)
        if aspect < MIN_ASPECT or aspect > MAX_ASPECT:
            continue

        region = GreenRegion(
            cx=(minx + maxx) // 2,
            cy=(miny + maxy) // 2,
            area=area,
            bbox=(minx, miny, bw, bh),
        )
        if best is None or region.area > best.area:
            best = region

    return best


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Запустить Android-приложение и нажать зелёную кнопку."
    )
    parser.add_argument("package", help="Имя пакета, например com.example.app")
    parser.add_argument("--adb", default="adb", help="Путь к adb (по умолчанию 'adb')")
    parser.add_argument("-s", "--serial", help="Серийный номер устройства")
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="Таймаут поиска кнопки, сек (10)"
    )
    parser.add_argument(
        "--warmup", type=float, default=2.0, help="Ожидание запуска приложения, сек (2)"
    )
    args = parser.parse_args()

    adb = ADB(adb_path=args.adb, serial=args.serial)

    try:
        installed = adb.is_installed(args.package)
    except FileNotFoundError:
        print(
            f"Ошибка: adb не найден ('{args.adb}'). "
            "Убедитесь, что Android SDK Platform Tools в PATH.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not installed:
        print(f"Ошибка: пакет '{args.package}' не установлен на устройстве.", file=sys.stderr)
        sys.exit(1)

    print(f"Запускаю '{args.package}'...")
    try:
        adb.launch_app(args.package)
    except subprocess.CalledProcessError as e:
        print(f"Ошибка запуска: {e.stderr.decode(errors='replace')}", file=sys.stderr)
        sys.exit(1)

    time.sleep(args.warmup)

    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        try:
            img = adb.screenshot()
        except subprocess.CalledProcessError as e:
            print(f"Ошибка скриншота: {e.stderr.decode(errors='replace')}", file=sys.stderr)
            sys.exit(1)

        region = find_green_region(img)
        if region:
            print(
                f"Найдена зелёная кнопка: центр=({region.cx}, {region.cy}), "
                f"площадь={region.area} px"
            )
            adb.tap(region.cx, region.cy)
            print("Нажатие выполнено.")
            return

        time.sleep(0.5)

    print("Зелёная кнопка не найдена (истёк таймаут).")
    sys.exit(1)


if __name__ == "__main__":
    main()
