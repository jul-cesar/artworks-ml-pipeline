import csv
import os
from collections.abc import Iterator
from pathlib import Path

from dotenv import load_dotenv

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def normalize_name(value: str) -> str:
    return " ".join(value.replace("_", " ").split()).casefold()


def parse_port(value: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise ValueError("MYSQL_PORT debe ser un número entero") from error


def find_artists_csv(root: Path) -> Path:
    for path in root.rglob("*"):
        if path.is_file() and path.name.casefold() == "artists.csv":
            return path
    raise FileNotFoundError(f"No se encontró artists.csv en {root}")


def find_image_root(root: Path) -> Path:
    directories = [path for path in root.rglob("*") if path.is_dir()]
    for preferred_name in ("resized", "images"):
        for path in sorted(directories):
            if path.name.casefold() == preferred_name:
                return path
    raise FileNotFoundError(f"No se encontró un directorio resized o images en {root}")


def iter_images(root: Path) -> Iterator[Path]:
    return (
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.casefold() in IMAGE_EXTENSIONS
    )


def match_artworks(
    dataset_root: Path,
    image_root: Path,
    artist_ids: dict[str, int],
) -> tuple[list[tuple[int, str, str]], set[str]]:
    rows: list[tuple[int, str, str]] = []
    unknown: set[str] = set()

    for image in iter_images(image_root):
        artist_name = image.parent.name
        artist_id = artist_ids.get(normalize_name(artist_name))
        if artist_id is None:
            filename_artist = image.stem.rsplit("_", 1)[0]
            if filename_artist != image.stem:
                artist_name = filename_artist
                artist_id = artist_ids.get(normalize_name(artist_name))
        if artist_id is None:
            unknown.add(" ".join(artist_name.replace("_", " ").split()))
            continue
        rows.append((artist_id, image.name, image.relative_to(dataset_root).as_posix()))

    return rows, unknown


def require_artworks(rows: list[tuple[int, str, str]], image_root: Path) -> None:
    if not rows:
        raise FileNotFoundError(
            f"No se encontraron imágenes relacionables en {image_root}"
        )


def main() -> None:
    load_dotenv()

    required = ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise ValueError(f"Faltan variables de entorno: {', '.join(missing)}")

    import kagglehub
    import mysql.connector

    dataset_root = Path(
        kagglehub.dataset_download("ikarus777/best-artworks-of-all-time")
    )
    artists_csv = find_artists_csv(dataset_root)
    image_root = find_image_root(dataset_root)

    with artists_csv.open(encoding="utf-8-sig", newline="") as file:
        artists = list(csv.DictReader(file))
    if not artists:
        raise ValueError(f"{artists_csv} no contiene artistas")

    connection_options: dict[str, object] = {
        "host": os.environ["MYSQL_HOST"],
        "port": parse_port(os.getenv("MYSQL_PORT", "3306")),
        "user": os.environ["MYSQL_USER"],
        "password": os.environ["MYSQL_PASSWORD"],
        "database": os.getenv("MYSQL_DATABASE", "cc-bd"),
    }
    if ssl_ca := os.getenv("MYSQL_SSL_CA"):
        connection_options.update(
            ssl_ca=ssl_ca,
            ssl_verify_cert=True,
            ssl_verify_identity=True,
        )

    connection = mysql.connector.connect(**connection_options)
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS artists (
                id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE,
                years VARCHAR(100),
                genre VARCHAR(255),
                nationality VARCHAR(255),
                bio LONGTEXT,
                wikipedia TEXT,
                paintings INT UNSIGNED
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS artworks (
                id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                artist_id BIGINT UNSIGNED NOT NULL,
                filename VARCHAR(255) NOT NULL,
                relative_path VARCHAR(512) NOT NULL UNIQUE,
                CONSTRAINT fk_artworks_artist
                    FOREIGN KEY (artist_id) REFERENCES artists(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

        artist_ids: dict[str, int] = {}
        for artist in artists:
            name = (artist.get("name") or "").strip()
            if not name:
                raise ValueError("artists.csv contiene un artista sin nombre")
            paintings_value = (artist.get("paintings") or "").strip()
            paintings = int(paintings_value) if paintings_value else None
            cursor.execute(
                """
                INSERT INTO artists
                    (name, years, genre, nationality, bio, wikipedia, paintings)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    id=LAST_INSERT_ID(id),
                    years=VALUES(years),
                    genre=VALUES(genre),
                    nationality=VALUES(nationality),
                    bio=VALUES(bio),
                    wikipedia=VALUES(wikipedia),
                    paintings=VALUES(paintings)
                """,
                (
                    name,
                    artist.get("years"),
                    artist.get("genre"),
                    artist.get("nationality"),
                    artist.get("bio"),
                    artist.get("wikipedia"),
                    paintings,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError(f"MySQL no devolvió el id del artista {name}")
            artist_ids[normalize_name(name)] = int(cursor.lastrowid)

        artwork_rows, unknown = match_artworks(
            dataset_root,
            image_root,
            artist_ids,
        )
        require_artworks(artwork_rows, image_root)
        batch_size = 1000
        for start in range(0, len(artwork_rows), batch_size):
            cursor.executemany(
                """
                INSERT INTO artworks (artist_id, filename, relative_path)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    artist_id=VALUES(artist_id),
                    filename=VALUES(filename)
                """,
                artwork_rows[start : start + batch_size],
            )

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()

    print(f"Artistas insertados o actualizados: {len(artist_ids)}")
    print(f"Imágenes registradas: {len(artwork_rows)}")
    print(f"Carpetas sin relación: {len(unknown)}")
    for folder in sorted(unknown):
        print(f"  - {folder}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(f"Error: {error}") from error
