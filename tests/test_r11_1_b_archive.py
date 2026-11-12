# tests/test_r11_1_b_archive.py -- R11.1 Part B (plan D10-D11): a zip (and a folder the console
# packed) is read member by member, each as its own kind, inside its caps; a zip bomb, a nested
# archive, a path that points outside, a password and too many files are refused in plain words
# before anything is unpacked; a picture is checked by its structure only, loses its camera and
# location data, and is refused when it is too large; and the child process that reads a hostile
# file is killed on time.
from __future__ import annotations

import asyncio
import time

import pytest
from r11_1_fakes_b import (
    alive,
    encrypted_zip,
    escaping_zip,
    make_jpeg,
    make_png,
    make_pptx,
    make_zip,
    many_sheets_xlsx,
    nested_zip,
    slow_xlsx,
    study_plan_xlsx,
    zip_bomb,
)

import jarvis.documents.isolation as isolation
from jarvis.documents.extract import Limits, extract
from jarvis.documents.isolation import Sandbox, extract_isolated
from jarvis.documents.limits import PICTURE_MAX_SIDE, DocumentRejected

GPS = b"GPS-LAT-12.97-LON-77.59"


def rejected(fn, *a, **kw) -> DocumentRejected:  # type: ignore[no-untyped-def]
    with pytest.raises(DocumentRejected) as e:
        fn(*a, **kw)
    return e.value


# ---- a zip is read member by member --------------------------------------------------------------


def bundle() -> bytes:
    return make_zip(
        {
            "plan.csv": b"Session,Topic\n1,Made-up topic one\n2,Made-up topic two\n",
            "notes/read me.md": b"# Made-up notes\nBring the plan.",
            "deck.pptx": make_pptx([(["Made-up deck"], [])]),
            "sheet.xlsx": study_plan_xlsx(3),
            "logo.gif": b"GIF89a....",
            "photo.jpg": make_jpeg(exif=GPS),
            "__MACOSX/._plan.csv": b"junk",
            "notes/": b"",
        }
    )


def test_a_zip_is_read_file_by_file_each_as_its_own_kind() -> None:
    out = extract(bundle(), "zip")
    assert out.kind == "zip" and (out.files, out.skipped) == (5, 1) and not out.truncated
    assert out.text.startswith(
        "Zip file: 5 files read, 1 not read.\n\nFile 1 of 5: plan.csv (CSV)\n"
    )
    assert "Session,Topic\n1,Made-up topic one" in out.text
    assert "notes/read me.md (Markdown)\n# Made-up notes" in out.text
    assert "deck.pptx (PowerPoint)\nSlide 1 of 1\nMade-up deck" in out.text
    assert "sheet.xlsx (Excel)\nSheet 1 of 2: Plan" in out.text
    assert "File 5 of 5: photo.jpg (a picture: shown with this message" in out.text
    assert out.text.rstrip().endswith("Not read: logo.gif (not a kind JARVIS reads).")
    assert "__MACOSX" not in out.text  # a Mac's own leftovers are not worth a line
    assert (out.sheets, out.rows) == (2, 6)


def test_a_picture_inside_a_zip_comes_out_clean() -> None:
    out = extract(bundle(), "zip")
    (pic,) = out.pictures
    assert (pic.name, pic.media_type) == ("photo.jpg", "image/jpeg")
    assert (
        GPS not in pic.data and pic.data.startswith(b"\xff\xd8") and pic.data.endswith(b"\xff\xd9")
    )


def test_only_four_pictures_are_taken_from_one_zip() -> None:
    files = {f"p{i}.png": make_png() for i in range(6)}
    out = extract(make_zip(files), "zip")
    assert len(out.pictures) == 4 and (out.files, out.skipped) == (4, 2)
    assert "p4.png (only 4 pictures are read from one zip)" in out.text


def test_a_member_that_cannot_be_read_is_said_and_the_rest_still_are() -> None:
    files = {
        "ok.txt": b"fine words",
        "broken.pdf": b"%PDF-1.4 not really",
        "huge.xlsx": many_sheets_xlsx(60),
        "fake.txt": b"\x89PNG\r\n\x1a\n" + b"\0" * 40,
    }
    out = extract(make_zip(files), "zip")
    assert (out.files, out.skipped) == (1, 3) and "fine words" in out.text
    tail = out.text[out.text.index("Not read: ") :]
    assert "broken.pdf (could not be read)" in tail
    assert "huge.xlsx (too large or unusual)" in tail
    assert "fake.txt (its contents don't match its name)" in tail


def test_the_character_cap_covers_the_whole_zip() -> None:
    files = {f"{i}.txt": (f"file {i} " + "word " * 400).encode() for i in range(5)}
    out = extract(make_zip(files), "zip", Limits(max_chars=3_000))
    assert out.truncated and len(out.text) <= 3_000
    assert out.files is not None and out.files < 5 and out.skipped >= 1


def test_a_zip_with_nothing_readable_says_so() -> None:
    e = rejected(extract, make_zip({"a.gif": b"GIF89a", "b.exe": b"MZ"}), "zip")
    assert e.code == "no_text" and "Nothing in this zip could be read" in str(e)
    assert rejected(extract, make_zip({}), "zip").code == "no_text"


# ---- refused before anything is unpacked ---------------------------------------------------------


def test_a_zip_bomb_is_refused_from_its_directory_alone(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import zipfile

    def never(*_: object, **__: object) -> bytes:
        raise AssertionError("a bomb must be refused before any member is unpacked")

    monkeypatch.setattr(zipfile.ZipFile, "read", never)
    e = rejected(extract, zip_bomb(60), "zip")
    assert e.code == "too_complex" and "zip bomb" in str(e) and "40 MB" in str(e)


def test_a_small_member_packed_too_tightly_is_a_bomb_too() -> None:
    e = rejected(extract, make_zip({"a.txt": b"0" * (8 * 1024 * 1024)}), "zip")
    assert e.code == "too_complex"


def test_a_nested_archive_is_refused() -> None:
    e = rejected(extract, nested_zip(), "zip")
    assert e.code == "unsafe_archive" and "another archive inside" in str(e)
    for inner in ("a.tar.gz", "b.7z", "c.RAR", "d.jar"):
        assert rejected(extract, make_zip({"ok.txt": b"x", inner: b"x"}), "zip").code == (
            "unsafe_archive"
        )


@pytest.mark.parametrize(
    "name",
    ["../../outside.txt", "/etc/passwd.txt", "C:/Users/x/a.txt", "a/../../b.txt", "..\\up.txt"],
)
def test_a_member_path_that_points_outside_is_refused(name: str) -> None:
    e = rejected(extract, escaping_zip(name), "zip")
    assert e.code == "unsafe_archive" and "outside the zip" in str(e)
    assert "outside.txt" not in str(e) and "passwd" not in str(e)  # the path is never repeated


def test_a_password_protected_zip_is_refused() -> None:
    e = rejected(extract, encrypted_zip(), "zip")
    assert e.code == "encrypted" and "password" in str(e)


def test_more_files_than_the_cap_is_refused_never_half_read() -> None:
    files = {f"{i}.txt": b"x" for i in range(6)}
    e = rejected(extract, make_zip(files), "zip", Limits(archive_max_files=5))
    assert e.code == "too_complex" and "6 files" in str(e) and "up to 5" in str(e)
    assert extract(make_zip(files), "zip", Limits(archive_max_files=6)).files == 6


def test_something_that_is_not_a_zip_is_refused() -> None:
    assert rejected(extract, b"plain words", "zip").code == "unsupported"
    assert rejected(extract, b"PK\x03\x04 broken", "zip").code == "unreadable"


def test_a_folder_reads_like_a_zip_and_calls_itself_a_folder() -> None:
    packed = make_zip({"plan/a.txt": b"alpha", "plan/sub/b.csv": b"k,v\n1,2"}, stored=True)
    out = extract(packed, "folder")
    assert out.kind == "folder" and out.files == 2
    assert out.text.startswith("Folder: 2 files read.\n\nFile 1 of 2: plan/a.txt (text)\nalpha")
    e = rejected(extract, nested_zip(), "folder")
    assert e.code == "unsafe_archive" and "folder" in str(e)


# ---- pictures: structure only, never decoded -----------------------------------------------------


def test_a_jpeg_loses_its_camera_and_location_data() -> None:
    out = extract(make_jpeg(exif=GPS), "image")
    (pic,) = out.pictures
    assert out.kind == "image" and out.text == "" and pic.media_type == "image/jpeg"
    assert GPS not in pic.data and b"Exif" not in pic.data


def test_a_png_keeps_its_pixels_and_loses_everything_else() -> None:
    src = make_png(8, 6, text=GPS) + b"TRAILING-SECRET"
    (pic,) = extract(src, "image").pictures
    assert pic.media_type == "image/png" and pic.data == make_png(8, 6)
    assert GPS not in pic.data and b"TRAILING" not in pic.data


def test_an_oversized_picture_is_refused_in_plain_words() -> None:
    side = PICTURE_MAX_SIDE + 1
    for big in (make_jpeg(side, 10), make_png(4, 4, declared=(10, side))):
        e = rejected(extract, big, "image")
        assert e.code == "too_large" and e.status == 413
        assert f"{side:,}" in str(e) and "2,048 pixels" in str(e)
    heavy = rejected(extract, make_jpeg(pad=4_000), "image", Limits(picture_max_bytes=2_000))
    assert heavy.code == "too_large" and "KB" in str(heavy) and "smaller" in str(heavy)


@pytest.mark.parametrize(
    "bad",
    [
        b"\x89PNG\r\n\x1a\n" + b"\0" * 30,  # no header chunk
        make_png()[:-12],  # no end
        make_png()[:40] + b"\xff" + make_png()[41:],  # a broken checksum
        b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\0" * 30,  # a JPEG with no picture in it
    ],
)
def test_a_damaged_picture_is_refused_never_passed_on(bad: bytes) -> None:
    e = rejected(extract, bad, "image")
    assert e.code == "bad_picture" and "couldn't be read" in str(e)


def test_a_picture_must_be_what_its_name_says() -> None:
    assert rejected(extract, b"GIF89a" + b"\0" * 20, "image").code == "unsupported"
    assert rejected(extract, b"<svg onload='x'/>", "image").code == "unsupported"


# ---- the child process: caps and the kill --------------------------------------------------------


async def test_the_child_hands_back_a_zips_text_counts_and_clean_pictures() -> None:
    out = await extract_isolated(bundle(), "zip", Limits())
    assert (out.files, out.skipped) == (5, 1) and len(out.pictures) == 1
    assert GPS not in out.pictures[0].data and out.text.startswith("Zip file: 5 files read")


@pytest.mark.parametrize(
    ("data", "kind", "code"),
    [
        (zip_bomb(60), "zip", "too_complex"),
        (nested_zip(), "zip", "unsafe_archive"),
        (escaping_zip(), "zip", "unsafe_archive"),
        (many_sheets_xlsx(300), "xlsx", "too_complex"),
        (make_jpeg(4_000, 3_000), "image", "too_large"),
    ],
)
async def test_each_hostile_file_is_refused_by_the_child_in_plain_words(
    data: bytes, kind: str, code: str
) -> None:
    with pytest.raises(DocumentRejected) as e:
        await extract_isolated(data, kind, Limits())
    assert e.value.code == code and 20 < len(str(e.value)) <= 500
    assert "Traceback" not in str(e.value) and "Error" not in str(e.value)


async def test_a_child_that_reads_too_long_is_killed_on_time(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    procs: list[asyncio.subprocess.Process] = []
    real = asyncio.create_subprocess_exec

    async def spy(*cmd, **kw):  # type: ignore[no-untyped-def]
        procs.append(await real(*cmd, **kw))
        return procs[-1]

    monkeypatch.setattr(isolation.asyncio, "create_subprocess_exec", spy)
    slow = slow_xlsx(9)
    started = time.monotonic()
    with pytest.raises(DocumentRejected) as e:
        await extract_isolated(slow, "xlsx", Limits(budget_s=60), Sandbox(timeout_s=0.4))
    took = time.monotonic() - started
    assert e.value.code == "too_slow" and took < 3.0
    assert len(procs) == 1 and not alive(procs[0].pid)


async def test_a_child_over_its_cpu_seconds_is_stopped_too() -> None:
    with pytest.raises(DocumentRejected) as e:
        await extract_isolated(
            slow_xlsx(9), "xlsx", Limits(budget_s=60, max_sheet_rows=10**9, max_chars=10**9),
            Sandbox(cpu_s=1, timeout_s=30),
        )  # fmt: skip
    assert e.value.code in ("too_slow", "too_complex")


async def test_a_picture_the_child_made_up_is_not_believed() -> None:
    limits = Limits()
    fake = (
        b'{"ok": true, "text": "", "truncated": false, "pictures": '
        b'[{"name": "x.jpg", "media_type": "image/jpeg", "data": "aGVsbG8="}]}'
    )
    with pytest.raises(DocumentRejected) as e:
        isolation.parse_output(fake, 0, kind="image", limits=limits)
    assert e.value.code == "unreadable"  # "hello" is not a JPEG
    five = b'{"ok": true, "text": "", "truncated": false, "pictures": [1, 2, 3, 4, 5]}'
    with pytest.raises(DocumentRejected):
        isolation.parse_output(five, 0, kind="zip", limits=limits)
