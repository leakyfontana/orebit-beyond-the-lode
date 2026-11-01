"""Frozen seeded-map and continued-RNG regression coverage."""
import hashlib
import json
import unittest

from terrain import HEIGHT, MIN_X, WIDTH, generate, tile_name


class TerrainTest(unittest.TestCase):
    # Captured from the original generator before the western extension. Western
    # fixtures continue that original loop for ten more columns, then apply only
    # Ria's slab (no western copies of the original fixed-building overrides).
    FINGERPRINTS = {
        0: (
            "8f2460df9278bf099923e1faed7e7e0031d10e1091e1f4608ff2e5b184ae50dc",
            "df7644cb4b23bb7c9ece0622328ffc068a491aa2d419b36a8f7ae931015efbc3",
        ),
        1: (
            "8b1f63e2e7df85afbee59da0611e4b3e8effc1be69e68b74107f7645253a4b63",
            "31bb350abf84c6a5d0b504c3fc81629b0f8813bb09a802be1d72b0ec7aa25a22",
        ),
        42: (
            "b2e908d6fbb761c1f39afe626cb0b703f6aee8d2fe550b6a908ed1f3f2d79142",
            "f7f25a52e80cc8272ef51c3105addc4a9684d518c00a3d5030dd581a2a5bcfef",
        ),
        -2147483648: (
            "a3ae272178f2270e86605b197bc93e1cce2c9d37e3b90a77453053693d5c9a1d",
            "ee93bfde4a15aba1b31adb095e5024f013045837407d0e1281876bcb0b87fcb0",
        ),
        2147483647: (
            "a3ae272178f2270e86605b197bc93e1cce2c9d37e3b90a77453053693d5c9a1d",
            "ee93bfde4a15aba1b31adb095e5024f013045837407d0e1281876bcb0b87fcb0",
        ),
    }

    def fingerprint(self, columns):
        return hashlib.sha256(json.dumps(columns, separators=(",", ":")).encode()).hexdigest()

    def test_original_domain_and_western_continuation_fingerprints(self):
        for seed, (original, western) in self.FINGERPRINTS.items():
            with self.subTest(seed=seed):
                terrain = generate(seed)
                self.assertIsInstance(terrain, dict)
                self.assertEqual(set(terrain), set(range(MIN_X, WIDTH)))
                self.assertEqual(self.fingerprint([terrain[x] for x in range(WIDTH)]), original)
                self.assertEqual(self.fingerprint([terrain[x] for x in range(MIN_X, 0)]), western)
                self.assertTrue(all(len(column) == HEIGHT for column in terrain.values()))
                self.assertTrue(all(terrain[-1] != terrain[x] for x in range(WIDTH)))
                with self.assertRaises(KeyError):
                    terrain[MIN_X - 1]
                with self.assertRaises(KeyError):
                    terrain[WIDTH]

    def test_western_surface_depth_rules_and_generated_resources(self):
        terrain = generate(42)
        names = set()
        for x in range(MIN_X, 0):
            self.assertEqual(terrain[x][:5], [0] * 5)
            surface = terrain[x][5]
            if -8 <= x <= -3:
                self.assertEqual(surface, -3 if x == -8 else (-5 if x == -3 else -4))
                self.assertEqual(tile_name(surface), "")
            else:
                self.assertIn(surface, (-1, -2))
            self.assertIn(terrain[x][HEIGHT - 12], (-7, -6))
            self.assertEqual(terrain[x][HEIGHT - 11:HEIGHT - 5], [-999] * 6)
            self.assertIn(terrain[x][HEIGHT - 5], (-9, -10, -11, -12))
            self.assertEqual(terrain[x][HEIGHT - 4:], [-8] * 4)
            underground = terrain[x][6:HEIGHT - 12]
            self.assertIn(0, underground)
            self.assertTrue(any(1 <= tile <= 5 for tile in underground))
            self.assertTrue(any(6 <= tile <= 15 for tile in underground))
            self.assertFalse(any(tile <= -100 for tile in underground))
            names.update(tile_name(tile) for tile in underground)
        self.assertTrue({"Dirt", "Ironium", "Rock", "Lava", "Gas"}.issubset(names))


if __name__ == "__main__":
    unittest.main()