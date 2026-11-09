import tempfile
import unittest
from pathlib import Path

from import_artworks import (
    find_artists_csv,
    find_image_root,
    iter_images,
    match_artworks,
    normalize_name,
    parse_port,
    require_artworks,
)


class ImportHelpersTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)

    def test_normalize_name_matches_folder_and_artist(self):
        self.assertEqual(
            normalize_name("Vincent_van_Gogh"),
            normalize_name("Vincent van Gogh"),
        )

    def test_parse_port_rejects_non_numeric_value(self):
        with self.assertRaisesRegex(ValueError, "MYSQL_PORT"):
            parse_port("abc")

    def test_require_artworks_rejects_empty_rows(self):
        with self.assertRaisesRegex(FileNotFoundError, "imágenes relacionables"):
            require_artworks([], self.root / "resized")

    def test_find_artists_csv_raises_when_missing(self):
        with self.assertRaisesRegex(FileNotFoundError, "artists.csv"):
            find_artists_csv(self.root)

    def test_find_image_root_prefers_resized(self):
        (self.root / "images").mkdir()
        (self.root / "resized").mkdir()

        self.assertEqual(find_image_root(self.root), self.root / "resized")

    def test_iter_images_ignores_non_images(self):
        (self.root / "work.jpg").touch()
        (self.root / "notes.txt").touch()

        self.assertEqual([path.name for path in iter_images(self.root)], ["work.jpg"])

    def test_find_image_root_uses_images_as_fallback(self):
        (self.root / "images").mkdir()

        self.assertEqual(find_image_root(self.root), self.root / "images")

    def test_find_image_root_raises_when_missing(self):
        with self.assertRaisesRegex(FileNotFoundError, "resized o images"):
            find_image_root(self.root)

    def test_match_artworks_matches_artist_folder_and_uppercase_extension(self):
        image_root = self.root / "images"
        artist_dir = image_root / "Vincent_van_Gogh"
        artist_dir.mkdir(parents=True)
        (artist_dir / "work.JPG").touch()

        rows, unknown = match_artworks(
            self.root,
            image_root,
            {"vincent van gogh": 7},
        )

        self.assertEqual(
            rows,
            [(7, "work.JPG", "images/Vincent_van_Gogh/work.JPG")],
        )
        self.assertEqual(unknown, set())

    def test_match_artworks_matches_artist_from_flat_resized_filename(self):
        image_root = self.root / "resized"
        image_root.mkdir()
        (image_root / "Vincent_van_Gogh_1.jpg").touch()

        rows, unknown = match_artworks(
            self.root,
            image_root,
            {"vincent van gogh": 7},
        )

        self.assertEqual(
            rows,
            [(7, "Vincent_van_Gogh_1.jpg", "resized/Vincent_van_Gogh_1.jpg")],
        )
        self.assertEqual(unknown, set())

    def test_match_artworks_reports_unknown_artist(self):
        image_root = self.root / "resized"
        artist_dir = image_root / "Unknown_Artist"
        artist_dir.mkdir(parents=True)
        (artist_dir / "work.jpg").touch()

        rows, unknown = match_artworks(self.root, image_root, {})

        self.assertEqual(rows, [])
        self.assertEqual(unknown, {"Unknown Artist"})


if __name__ == "__main__":
    unittest.main()
