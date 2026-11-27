import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class QuestSnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads((ROOT / "sources/quests.json").read_text(encoding="utf-8"))
        cls.quests = {quest["id"]: quest for quest in cls.snapshot["quests"]}

    def test_source_shape(self):
        source = self.snapshot["source"]
        self.assertEqual(source["language"], "chs")
        self.assertEqual(source["tailOffset"], 128)
        self.assertGreaterEqual(source["count"], 5300)
        self.assertEqual(len(self.quests), source["count"])
        self.assertGreater(source["textCount"], 5000)

    def test_chinese_fields_are_read(self):
        quest = self.quests[67140]
        self.assertEqual(quest["name"], "搜寻伊塞勒")
        self.assertEqual(quest["genre"], 3)
        self.assertEqual(quest["place"], 62)
        self.assertEqual(quest["sort"], 25)
        self.assertEqual(quest["rewards"]["gil"], 753)
        self.assertEqual(quest["rewards"]["items"], [[10074, 1]])
        self.assertGreater(len(quest["steps"]), 3)

    def test_rewards_and_series_links(self):
        quest = self.quests[70126]
        self.assertEqual(quest["genre"], 244)
        self.assertEqual(quest["place"], 53)
        self.assertEqual(quest["sort"], 221)
        self.assertEqual(quest["rewards"]["gil"], 679)
        self.assertEqual(quest["rewards"]["items"], [[36857, 1]])

    def test_labels_resolve(self):
        genres = self.snapshot["genres"]
        places = self.snapshot["places"]
        for quest in self.snapshot["quests"]:
            if quest["genre"]:
                self.assertIn(str(quest["genre"]), genres)
            if quest["place"]:
                self.assertIn(str(quest["place"]), places)
            self.assertGreaterEqual(quest["sort"], 0)


if __name__ == "__main__":
    unittest.main()
