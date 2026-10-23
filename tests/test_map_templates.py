import json
import tempfile
import unittest
from pathlib import Path

from yangyang_hunter.map_templates import (
    acquire_second_stage_template, second_stage_map_id,
)


MAP_ID = "b" * 32
SEED = {"map_md5": ["a" * 32, MAP_ID]}


def varint(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def number(field, value):
    return varint(field << 3) + varint(value)


def message(field, value):
    return varint((field << 3) | 2) + varint(len(value)) + value


def sample_map(preset=False):
    group = message(1, b"1") + number(2, 1)
    cards = []
    for index in range(3):
        card = (message(1, f"card-{index}".encode()) + number(2, 0) +
                number(3, index * 8) + number(4, 0) + number(5, 1))
        cards.append(message(1, card))
    if preset:
        for index in range(3, 6):
            card = (message(1, f"card-{index}".encode()) + number(2, 2) +
                    number(3, index * 8) + number(4, 0) + number(5, 1))
            cards.append(message(1, card))
    layer = message(1, b"1") + message(2, b"".join(cards))
    body = (number(1, 8) + number(2, 10) + number(3, 12345) +
            message(4, group) + message(5, layer))
    return b".map" + bytes(17) + body


class MapTemplateTests(unittest.TestCase):
    def test_second_stage_id_is_selected(self):
        self.assertEqual(second_stage_map_id(SEED), MAP_ID)
        with self.assertRaises(ValueError):
            second_stage_map_id({"map_md5": ["a" * 32, "../../unsafe"]})

    def test_recovers_captured_map(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            captures = root / "captures"
            captures.mkdir()
            raw = captures / "recorded.bin"
            raw.write_bytes(sample_map())
            (captures / "index.jsonl").write_text(json.dumps({
                "path": f"/maps/{MAP_ID}.map", "status": 200,
                "saved_file": raw.name,
            }) + "\n", encoding="utf-8")
            result = acquire_second_stage_template(
                SEED, root / "templates", captures, wait_seconds=0,
                downloader=lambda *_: self.fail("unexpected download"))
            data = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(data["sourceMapMd5"], MAP_ID)
            self.assertEqual(sum(map(len, data["levelData"].values())), 3)
            raw.unlink()
            (captures / "index.jsonl").unlink()
            cached = acquire_second_stage_template(
                SEED, root / "templates", captures, wait_seconds=0,
                downloader=lambda *_: self.fail("cached map was not reused"))
            self.assertEqual(cached, result)

    def test_downloads_when_capture_is_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            captures = root / "captures"

            def download(map_id, output):
                self.assertEqual(map_id, MAP_ID)
                raw = output / "downloaded.bin"
                raw.write_bytes(sample_map())
                return raw

            result = acquire_second_stage_template(
                SEED, root / "templates", captures, wait_seconds=0,
                downloader=download)
            self.assertTrue(result.is_file())
            self.assertEqual(second_stage_map_id(SEED), MAP_ID)

    def test_preset_cards_are_not_counted_as_seed_assigned_cards(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            captures = root / "captures"
            captures.mkdir()
            raw = captures / "recorded.bin"
            raw.write_bytes(sample_map(preset=True))
            (captures / "index.jsonl").write_text(json.dumps({
                "path": f"/maps/{MAP_ID}.map", "status": 200,
                "saved_file": raw.name,
            }) + "\n", encoding="utf-8")
            result = acquire_second_stage_template(
                SEED, root / "templates", captures, wait_seconds=0,
                downloader=lambda *_: self.fail("unexpected download"))
            data = json.loads(result.read_text(encoding="utf-8"))
            cards = [card for layer in data["levelData"].values() for card in layer]
            self.assertEqual(len(cards), 6)
            self.assertEqual(sum(card["type"] == 0 for card in cards), 3)
            self.assertEqual(sum(card["type"] == 2 for card in cards), 3)


if __name__ == "__main__":
    unittest.main()
