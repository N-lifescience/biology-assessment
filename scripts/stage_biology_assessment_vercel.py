"""Stage the publish databases into the API package tree for a Vercel deploy.

``services/biology-assessment-api/app/settings.py`` serves the catalog from
``services/biology-assessment-api/data/`` when the repository's own
``data/publish/`` tree is absent (it is gitignored and never deployed).  This
script produces exactly what ``materialized_packaged_database()`` reads back:
a gzip stream per database, split into ``<name>.sqlite.gz.part-NNN`` chunks
that ``MultipartReader`` concatenates in filename order, plus a
``release-manifest.json`` keyed by the *uncompressed* database name and hash.

Split threshold: 40 MB.  A Vercel Python function may be 500 MB uncompressed
(https://vercel.com/docs/functions/limitations) and both packages together are
~103 MB gzipped, so the function limit is not what binds here.  The binding
limit is per file: Vercel caps a Hobby deployment's source files at 100 MB
(https://vercel.com/docs/limits) and GitHub -- which is how this project
deploys -- hard-blocks any pushed file over 100 MB and warns over 50 MB.
Since ``services/biology-assessment-api/data/`` is committed (only the root
``/data/`` is gitignored), 40 MB parts stay under the warning with margin.

Usage:
    node scripts/run-python.mjs scripts/stage_biology_assessment_vercel.py
    node scripts/run-python.mjs scripts/stage_biology_assessment_vercel.py --self-check
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLISH_DIRECTORY = PROJECT_ROOT / "data" / "publish"
PACKAGED_DIRECTORY = PROJECT_ROOT / "services" / "biology-assessment-api" / "data"
RELEASE_MANIFEST_NAME = "release-manifest.json"
OFFICIAL_SOURCE_REGISTRY_NAME = "official_biology_source_registry.json"
MAX_PART_BYTES = 40 * 1024 * 1024

STAGED_DATABASES = (
    "biology_assessment_catalog.sqlite",
    "biology_assessment_catalog_detail.sqlite",
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clear_previous_package(destination: Path, gzip_name: str) -> None:
    """Drop every artifact of an earlier run for this database.

    ``MultipartReader`` concatenates *whatever* ``<name>.gz.part-*`` files it
    finds, so a part left over from a larger previous build would silently
    corrupt the stream.  Removing them first is the whole point of this step.
    """
    (destination / gzip_name).unlink(missing_ok=True)
    for stale in destination.glob(f"{gzip_name}.part-*"):
        stale.unlink()


def package_database(
    source: Path,
    destination: Path,
    *,
    max_part_bytes: int = MAX_PART_BYTES,
) -> list[Path]:
    """Compress ``source`` into ``destination``, splitting past ``max_part_bytes``."""
    destination.mkdir(parents=True, exist_ok=True)
    gzip_name = f"{source.name}.gz"
    clear_previous_package(destination, gzip_name)

    with tempfile.TemporaryDirectory(dir=destination) as scratch:
        staged = Path(scratch) / gzip_name
        # mtime=0 keeps the output byte-identical between runs, so re-staging an
        # unchanged database does not create a pointless multi-megabyte git diff.
        with source.open("rb") as raw:
            with gzip.GzipFile(filename=staged, mode="wb", compresslevel=9, mtime=0) as packed:
                shutil.copyfileobj(raw, packed, length=1024 * 1024)

        packed_size = staged.stat().st_size
        if packed_size <= max_part_bytes:
            written = [destination / gzip_name]
            staged.replace(written[0])
            return written

        written = []
        with staged.open("rb") as stream:
            index = 0
            while True:
                chunk = stream.read(max_part_bytes)
                if not chunk:
                    break
                # Zero padded: MultipartReader reads sorted(glob(...)), and
                # "part-10" would otherwise sort before "part-2".
                part = destination / f"{gzip_name}.part-{index:03d}"
                part.write_bytes(chunk)
                written.append(part)
                index += 1
    return written


def stage(
    publish_directory: Path = PUBLISH_DIRECTORY,
    packaged_directory: Path = PACKAGED_DIRECTORY,
    *,
    max_part_bytes: int = MAX_PART_BYTES,
    quiet: bool = False,
) -> dict:
    def log(message: str) -> None:
        if not quiet:
            print(message)

    missing = [
        name for name in STAGED_DATABASES if not (publish_directory / name).is_file()
    ]
    if missing:
        raise SystemExit(
            f"stage: missing publish database(s) in {publish_directory}: {', '.join(missing)}. "
            "Build the pipeline (scripts/run_final_biology_assessment_pipeline.py) first."
        )

    files = []
    for name in STAGED_DATABASES:
        source = publish_directory / name
        parts = package_database(source, packaged_directory, max_part_bytes=max_part_bytes)
        packed_bytes = sum(part.stat().st_size for part in parts)
        # The manifest records the uncompressed identity: settings.py looks the
        # entry up by ``packaged_database.name``, i.e. the ".sqlite" name.
        files.append({"name": name, "sha256": sha256_of(source)})
        log(
            f"stage: {name} {source.stat().st_size / 1048576:.1f} MB -> "
            f"{packed_bytes / 1048576:.1f} MB in {len(parts)} file(s): "
            f"{', '.join(part.name for part in parts)}"
        )

    manifest = {"files": files}
    manifest_path = packaged_directory / RELEASE_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    log(f"stage: wrote {manifest_path.name} for {len(files)} database(s)")

    registry_source = publish_directory / OFFICIAL_SOURCE_REGISTRY_NAME
    registry_target = packaged_directory / OFFICIAL_SOURCE_REGISTRY_NAME
    if registry_source.is_file():
        shutil.copyfile(registry_source, registry_target)
        log(f"stage: copied {OFFICIAL_SOURCE_REGISTRY_NAME}")
    elif registry_target.is_file():
        log(
            f"stage: WARNING {registry_source} is missing; keeping the already packaged "
            f"{OFFICIAL_SOURCE_REGISTRY_NAME} as-is."
        )
    else:
        log(
            f"stage: WARNING neither {registry_source} nor {registry_target} exists; "
            "the API will have no official source registry."
        )
    return manifest


def self_check() -> None:
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        publish = root / "publish"
        packaged = root / "packaged"
        publish.mkdir()

        # A real SQLite file: settings.py rejects a materialized database whose
        # first 16 bytes are not the SQLite magic, so the check must use one.
        for name in STAGED_DATABASES:
            connection = sqlite3.connect(publish / name)
            connection.execute("CREATE TABLE sample (value TEXT)")
            connection.executemany(
                "INSERT INTO sample VALUES (?)", [(f"{name}-{index}",) for index in range(4000)]
            )
            connection.commit()
            connection.close()

        catalog = publish / STAGED_DATABASES[0]
        original = catalog.read_bytes()

        parts = package_database(catalog, packaged, max_part_bytes=4096)
        assert len(parts) > 1, "a threshold below the payload must split the stream"
        names = [part.name for part in parts]
        assert names == sorted(names), f"parts must be written in sort order: {names}"

        # Reassembling in sorted-glob order is exactly what MultipartReader does.
        globbed = sorted(packaged.glob(f"{catalog.name}.gz.part-*"))
        rebuilt = gzip.decompress(b"".join(part.read_bytes() for part in globbed))
        assert rebuilt == original, "split parts did not round-trip to the source database"
        assert rebuilt[:16] == b"SQLite format 3\x00", "rebuilt payload is not a SQLite database"

        # Re-staging with a threshold that no longer splits must clear the old
        # parts, or MultipartReader would concatenate a stale tail onto the new one.
        single = package_database(catalog, packaged, max_part_bytes=100 * 1024 * 1024)
        assert len(single) == 1 and single[0].name.endswith(".gz"), single
        assert not list(packaged.glob("*.part-*")), "stale parts survived a re-run"
        assert gzip.decompress(single[0].read_bytes()) == original

        manifest = stage(publish, packaged, max_part_bytes=4096, quiet=True)
        recorded = {entry["name"]: entry["sha256"] for entry in manifest["files"]}
        assert set(recorded) == set(STAGED_DATABASES), recorded
        assert recorded[catalog.name] == hashlib.sha256(original).hexdigest()
        assert json.loads((packaged / RELEASE_MANIFEST_NAME).read_text("utf-8")) == manifest
    print("ok stage_biology_assessment_vercel self-check")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--publish", type=Path, default=PUBLISH_DIRECTORY)
    parser.add_argument("--packaged", type=Path, default=PACKAGED_DIRECTORY)
    parser.add_argument("--max-part-bytes", type=int, default=MAX_PART_BYTES)
    parser.add_argument("--self-check", action="store_true")
    arguments = parser.parse_args()

    if arguments.self_check:
        self_check()
        return
    stage(arguments.publish, arguments.packaged, max_part_bytes=arguments.max_part_bytes)


if __name__ == "__main__":
    main()
