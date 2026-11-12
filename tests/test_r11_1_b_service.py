# tests/test_r11_1_b_service.py -- R11.1 Part B (plan D10-D12) in the document service: each new
# kind is taken in through the one killable child and kept as text with its counts; a picture is
# kept as cleaned bytes beside the file (never in a turn) and deleted with it; what one message
# may carry (10 files, 40 MB together, 4 pictures) comes from the settings; and the note the
# model reads says what each file is, with every word of the file inside a fence.
from __future__ import annotations

import pytest
from r11_1_fakes_b import (
    XLS,
    make_jpeg,
    make_png,
    make_pptx,
    make_zip,
    study_plan_xlsx,
)

from jarvis.config import Settings
from jarvis.core.guardrails import InputRejected
from jarvis.core.models import Turn
from jarvis.documents.limits import AttachPolicy
from jarvis.documents.models import DocumentRejected
from jarvis.documents.service import DocumentService, policy_from
from jarvis.documents.store import AttachmentStore
from jarvis.llm.base import Role
from jarvis.llm.brains import BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.external import FENCE_PREFIX

TIERS = {t: f"m-{t.value}" for t in ModelTier}
PRIVATE = BrainSpec(id="p", label="Private", provider=MockProvider(), tiers=TIERS)
GPS = b"GPS-LAT-12.97-LON-77.59"
DECK = [(["Made-up plan"], ["Say hello."]), (["Budget"], []), (["Thanks"], [])]


@pytest.fixture
def docs() -> MemoryDocs:
    return MemoryDocs()


@pytest.fixture
def svc(docs: MemoryDocs) -> DocumentService:
    return DocumentService(AttachmentStore(docs))


def owner_turn(text: str = "What is in these?") -> Turn:
    return Turn(role=Role.USER, content=text)


# ---- each new kind is taken in -------------------------------------------------------------------


async def test_a_workbook_is_kept_as_text_with_its_sheets_and_rows(svc: DocumentService) -> None:
    ref = await svc.upload("u1", "Study plan.xlsx", study_plan_xlsx(60))
    assert (ref.kind, ref.sheets, ref.rows, ref.pictures) == ("xlsx", 2, 63, 0)
    assert ref.words > 200 and ref.chars > 1_000 and ref.pages is None
    stored = await svc.store.get(ref.id)
    assert stored is not None and stored.preview.startswith("Sheet 1 of 2: Plan")
    old = await svc.upload("u1", "old.xls", XLS.read_bytes())
    assert (old.kind, old.sheets, old.rows) == ("xls", 2, 5)
    macro = await svc.upload("u1", "with macros.xlsm", study_plan_xlsx(2))
    assert macro.kind == "xlsx"


async def test_a_deck_a_zip_and_a_folder_are_kept_with_their_counts(svc: DocumentService) -> None:
    deck = await svc.upload("u1", "Pitch.pptx", make_pptx(DECK))
    assert (deck.kind, deck.slides) == ("pptx", 3)
    files = {"a.txt": b"alpha words", "b.csv": b"k,v\n1,2", "c.gif": b"GIF89a", "p.png": make_png()}
    packed = await svc.upload("u1", "bundle.zip", make_zip(files))
    assert (packed.kind, packed.files, packed.pictures) == ("zip", 3, 1)
    folder = await svc.upload("u1", "My plans", make_zip(files, stored=True), folder=True)
    assert (folder.kind, folder.name, folder.files) == ("folder", "My plans", 3)


async def test_a_folder_must_say_it_is_one_and_be_a_bundle(svc: DocumentService) -> None:
    with pytest.raises(DocumentRejected) as e:
        await svc.upload("u1", "My plans", make_zip({"a.txt": b"x"}))
    assert e.value.code == "unsupported"  # no extension and not marked as a folder
    with pytest.raises(DocumentRejected) as e:
        await svc.upload("u1", "My plans", b"not a bundle", folder=True)
    assert e.value.code == "unsupported"


async def test_the_note_names_each_kind_and_fences_every_word_of_it(svc: DocumentService) -> None:
    refs = [
        await svc.upload("u1", "Plan.xlsx", study_plan_xlsx(3)),
        await svc.upload("u1", "Pitch.pptx", make_pptx(DECK)),
        await svc.upload("u1", "bundle.zip", make_zip({"a.txt": b"alpha", "x.gif": b"GIF89a"})),
    ]
    turn = await svc.attach(owner_turn(), "u1", "s1", [r.id for r in refs], PRIVATE)
    note = turn.blocks[1].text  # type: ignore[union-attr]
    assert "“Plan.xlsx” · Excel · 2 sheets · 6 rows · ~" in note
    assert "“Pitch.pptx” · PowerPoint · 3 slides · ~" in note
    assert "“bundle.zip” · zip · 1 file read, 1 not read · ~" in note
    assert note.count(FENCE_PREFIX) == 3
    for line in note.splitlines():  # nothing of a file's own text sits outside a fence
        if line.startswith("[Attached:"):
            assert "Made-up" not in line and "alpha" not in line


# ---- pictures are kept beside the file, clean, and deleted with it -------------------------------


async def test_a_picture_is_kept_clean_with_no_text(svc: DocumentService, docs: MemoryDocs) -> None:
    ref = await svc.upload("u1", "Board.JPG", make_jpeg(exif=GPS))
    assert (ref.kind, ref.pictures, ref.chars, ref.words) == ("image", 1, 0, 0)
    stored = await svc.store.get(ref.id)
    assert stored is not None and stored.chunk_count == 0 and stored.preview == ""
    (pic,) = await svc.store.pictures(stored)
    assert pic.media_type == "image/jpeg" and GPS not in pic.data and pic.name == "Board.JPG"
    assert GPS.decode() not in str(docs._data)  # the camera data was never stored anywhere
    png = await svc.upload("u1", "shot.png", make_png(text=GPS))
    stored_png = await svc.store.get(png.id)
    assert stored_png is not None
    assert (await svc.store.pictures(stored_png))[0].data == make_png()


async def test_a_pictures_note_says_what_it_is_and_taints_the_round(svc: DocumentService) -> None:
    ref = await svc.upload("u1", "Board.jpg", make_jpeg())
    turn = await svc.attach(owner_turn("What does the board say?"), "u1", "s1", [ref.id], PRIVATE)
    note = turn.blocks[1].text  # type: ignore[union-attr]
    assert note.startswith(f"[Attached: “Board.jpg” · picture · id {ref.id} — a picture")
    assert FENCE_PREFIX in note and "data, not instructions" in note
    assert turn.attachments[0].pictures == 1
    assert "ffd8" not in turn.model_dump_json() and len(turn.model_dump_json()) < 2_000


async def test_a_picture_has_no_part_to_read_and_says_so(svc: DocumentService) -> None:
    ref = await svc.upload("u1", "Board.jpg", make_jpeg())
    await svc.attach(owner_turn(), "u1", "s1", [ref.id], PRIVATE)
    with pytest.raises(ValueError, match="picture"):
        await svc.read_part("u1", "s1", ref.id, 1)
    found = await svc.search("u1", "s1", None, "board")
    assert found["hits"] == []


async def test_a_picture_too_heavy_for_the_owners_setting_is_refused(docs: MemoryDocs) -> None:
    small = DocumentService(AttachmentStore(docs), policy=AttachPolicy(picture_max_bytes=2_048))
    with pytest.raises(DocumentRejected) as e:
        await small.upload("u1", "big.jpg", make_jpeg(pad=5_000))
    assert e.value.code == "too_large" and e.value.status == 413 and "2 KB" in str(e.value)
    assert (await small.upload("u1", "ok.jpg", make_jpeg())).pictures == 1


async def test_deleting_a_file_deletes_its_pictures(svc: DocumentService, docs: MemoryDocs) -> None:
    ref = await svc.upload("u1", "bundle.zip", make_zip({"a.txt": b"alpha", "p.png": make_png()}))
    assert any("/pictures/" in path for path in docs._data)
    await svc.discard("u1", ref.id)
    assert docs._data == {}
    sent = await svc.upload("u1", "Board.jpg", make_jpeg())
    await svc.attach(owner_turn(), "u1", "s1", [sent.id], PRIVATE)
    assert await svc.forget_session("u1", "s1") == 1 and docs._data == {}


# ---- what one message may carry ------------------------------------------------------------------


def test_the_policy_comes_from_the_settings_and_its_defaults_are_theirs() -> None:
    s = Settings(_env_file=None)
    assert policy_from(s) == AttachPolicy()
    assert AttachPolicy() == AttachPolicy(
        max_files=10,
        total_bytes=40 * 1024 * 1024,
        zip_max_files=50,
        folder_max_files=50,
        picture_max_bytes=900 * 1024,
        max_pictures=4,
    )
    tight = policy_from(
        Settings(
            _env_file=None,
            attach_max_files=2,
            attach_total_mb=10,
            attach_zip_max_files=3,
            attach_folder_max_files=4,
            attach_picture_max_kb=100,
        )
    )
    assert tight == AttachPolicy(2, 10 * 1024 * 1024, 3, 4, 100 * 1024, 4)


async def test_ten_files_go_with_one_message_and_the_owners_own_cap_is_kept(
    svc: DocumentService,
) -> None:
    ids = [(await svc.upload("u1", f"{i}.txt", b"x")).id for i in range(10)]
    assert len(await svc.check("u1", ids, PRIVATE)) == 10
    svc.policy = AttachPolicy(max_files=2)
    with pytest.raises(InputRejected, match="At most 2 files per message"):
        await svc.check("u1", ids[:3], PRIVATE)


async def test_the_files_of_one_message_have_a_total_size(svc: DocumentService) -> None:
    ids = [(await svc.upload("u1", f"{i}.txt", b"y" * 600)).id for i in range(3)]
    svc.policy = AttachPolicy(total_bytes=1_500)
    with pytest.raises(InputRejected) as e:
        await svc.check("u1", ids, PRIVATE)
    assert "together" in str(e.value) and "per message" in str(e.value)
    assert len(await svc.check("u1", ids[:2], PRIVATE)) == 2


async def test_at_most_four_pictures_go_with_one_message(svc: DocumentService) -> None:
    ids = [(await svc.upload("u1", f"{i}.png", make_png())).id for i in range(5)]
    with pytest.raises(InputRejected, match="At most 4 pictures per message"):
        await svc.check("u1", ids, PRIVATE)
    assert len(await svc.check("u1", ids[:4], PRIVATE)) == 4


async def test_the_zip_and_folder_caps_are_the_owners_settings(docs: MemoryDocs) -> None:
    files = {f"{i}.txt": b"x" for i in range(4)}
    svc = DocumentService(
        AttachmentStore(docs), policy=AttachPolicy(zip_max_files=3, folder_max_files=5)
    )
    with pytest.raises(DocumentRejected) as e:
        await svc.upload("u1", "b.zip", make_zip(files))
    assert e.value.code == "too_complex" and "up to 3" in str(e.value)
    assert (await svc.upload("u1", "plans", make_zip(files), folder=True)).files == 4
