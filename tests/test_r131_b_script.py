# tests/test_r131_b_script.py -- R13.1 Part B (docs/plans/r13-1-try-on.md D3): the mannequin's build
# script (scripts/mannequin), tested on SYNTHETIC meshes and a made-up source clone (tests/
# r131_fakes_b.py): the mesh helpers, the Newton solve, the measure rig, the GLB writer and reader,
# the source table's refusals ("never reads smplx"), the size rules. numpy and scipy are the build's
# own pins (a dev tool): without them these tests are skipped, never failed.
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from r131_fakes_b import SCRIPTS, fake_clone, mannequin, tube  # noqa: E402

mq = mannequin()
from mannequin import build, core, glb, measure, mesh  # noqa: E402


# ---- the mesh helpers ----------------------------------------------------------------------------
def test_quads_become_two_triangles_and_normals_point_out_of_a_tube() -> None:
    x, q = tube()
    t = mesh.tri_of(q)
    assert len(t) == 2 * len(q)
    n = mesh.vnormals(x, t)
    radial = x * [1, 0, 1] / 0.1
    assert ((n * radial).sum(1) > 0.9).all()


def test_taubin_smoothing_keeps_a_tubes_size_and_its_open_edges_are_two_rings() -> None:
    x, q = tube(around=24, up=10)
    t = mesh.tri_of(q)
    assert len(mesh.boundary_verts(t)) == 48
    y = mesh.taubin(x, mesh.avg_matrix(len(x), t), 3)
    inner = slice(24, -24)
    assert np.abs(np.hypot(y[inner, 0], y[inner, 2]) - 0.1).max() < 0.004


def test_a_slice_measures_the_radius_at_every_angle_and_fills_what_it_misses() -> None:
    x, q = tube(radius=0.2, around=32)
    r = mesh.slice_r(x, mesh.tri_of(q), mesh.frame([0, 0, 0], mesh.UP), 0.26, np.linspace(0, 6, 9))
    assert np.abs(r - 0.2).max() < 0.002
    with pytest.raises(RuntimeError, match="empty slice"):
        mesh.slice_r(x, mesh.tri_of(q), mesh.frame([0, 0, 0], mesh.UP), 9.0, np.array([0.0]))


def test_a_loft_has_a_fixed_topology_and_its_uvs_are_in_metres() -> None:
    th = np.arange(8) / 8 * 2 * np.pi
    fr = mesh.frame([0, 0, 0], mesh.UP)
    rings = [mesh.ring_pts(fr, h, th, 0.1) for h in (0.0, 0.3, 0.6)]
    x, t = mesh.loft(rings)
    assert (len(x), len(t)) == (24, 32)
    xc, tc = mesh.loft(rings, cap_end=True)
    assert (len(xc), len(tc)) == (25, 40)
    uv = mesh.loft_uv(rings)
    assert uv[:, 1].max() == pytest.approx(0.6) and uv[1, 0] == pytest.approx(
        2 * 0.1 * np.sin(np.pi / 8)
    )


def test_welding_splits_a_vertex_only_on_a_uv_seam() -> None:
    x, q = tube(around=12, up=3)
    t = mesh.tri_of(q)
    cuv = mesh.cyl_uv(x, t, mesh.frame([0, 0, 0], mesh.UP), 0.1)
    vmap, t2, uv = mesh.weld(t, cuv)
    assert len(vmap) == len(x) + 3 and len(uv) == len(vmap)  # one seam column of three points
    assert (vmap[t2] == t).all()


def test_pieces_that_face_inward_are_flipped_and_a_band_is_judged_from_the_axis() -> None:
    x, q = tube()
    t = mesh.tri_of(q)[:, ::-1]  # wound inside out
    fixed = mesh.orient_out(x, t, 0.0, [])
    assert ((mesh.vnormals(x, fixed) * x * [1, 0, 1]).sum(1) > 0).all()
    band = np.array([[-0.01, 0.0, 0.1], [0.01, 0.0, 0.1], [0.01, 0.1, 0.1], [-0.01, 0.1, 0.1]])
    bt = np.array([[0, 2, 1], [0, 3, 2]])  # facing -z: towards the axis
    out = mesh.orient_out(band, bt, 0.0, [(0, 4)])
    assert (mesh.vnormals(band, out)[:, 2] > 0.9).all()


def test_smoothstep_runs_both_ways_and_a_ring_of_radii_is_smoothed_in_place() -> None:
    assert mesh.smoothstep(0, 1, 0.5) == pytest.approx(0.5)
    assert mesh.smoothstep(1, 0, 0.25) == pytest.approx(mesh.smoothstep(0, 1, 0.75))
    r = np.array([1.0, 0, 0, 0])
    assert mesh.circ_smooth(r, 1).tolist() == [0.5, 0.25, 0.0, 0.25]


# ---- the solve and the measurements --------------------------------------------------------------
def test_newton_steps_reach_six_wanted_numbers() -> None:
    a_ = np.eye(6) * 40 + 3

    def f(a: Any) -> Any:
        return a_ @ a + 0.5 * np.sin(a) + 100

    want = np.array([172.0, 44, 96, 82, 96, 79])
    got = measure.solve(f, want, np.zeros(6), iters=8)
    assert np.abs(f(got) - want).max() < 0.02


def test_the_six_measurements_of_a_made_up_rig() -> None:
    x, q = tube(radius=0.15, height=2.0, around=64, up=41)
    e = np.unique(
        np.sort(np.concatenate([q[:, [0, 1]], q[:, [1, 2]], q[:, [2, 3]], q[:, [3, 0]]]), 1), axis=0
    )
    waist = x[64 * 20 : 64 * 21]  # the ring at y = 1.0
    mid = np.array([[0, 0.7, 0.15], [0, 1.2, 0.15]])
    sh = np.array([[0.2, 1.5, 0], [-0.2, 1.5, 0]])
    got = measure.six(2.0, 0.0, sh, waist, mid, x, e)
    girth = 2 * 64 * 0.15 * np.sin(np.pi / 64) * 100
    assert got == pytest.approx([200, 40, girth, girth, girth, 70], abs=0.3)


def test_the_weights_are_the_servers_rule_and_the_table_has_its_cases() -> None:
    from jarvis.wardrobe.tryon import model

    assert measure.MEASURES == model.MEASURES and dict(measure.SAMPLE) == dict(model.SAMPLE)
    assert {k: tuple(v) for k, v in measure.RANGES.items()} == dict(model.RANGES)
    for vals in (
        {**measure.SAMPLE, "waist": 62},
        {**measure.SAMPLE, "waist": 101, "height": 150},
        {**measure.SAMPLE, "chest": 124, "inseam": 66},
    ):
        mine = measure.weights_of(vals)
        assert {k: round(v, 6) for k, v in mine.items()} == model.morph_weights(vals)
    cases = measure.table_cases()
    assert len(cases) == 1 + 12 + 4 + 2 and cases[0][0] == "sample"


def test_a_rig_mesh_is_measured_through_its_morphs() -> None:
    x, q = tube(radius=0.15, height=2.0, around=32, up=41)
    e = np.unique(
        np.sort(np.concatenate([q[:, [0, 1]], q[:, [1, 2]], q[:, [2, 3]], q[:, [3, 0]]]), 1), axis=0
    )
    ring = np.arange(32 * 20, 32 * 21)
    extra = np.array(
        [[0, 2.0, 0], [0, 0.0, 0], [0.2, 1.5, 0], [-0.2, 1.5, 0], [0, 0.7, 0.15], [0, 1.2, 0.15]]
    )
    pts = np.concatenate([extra, x[ring], x])
    sections = {"ends": [0, 2], "shoulders": [2, 2], "mid": [4, 2], "waist": [6, 32]}
    rig = dict(
        x=pts, index=e + 38, targets={"height": pts * [0, 0.1, 0]}, extras=dict(sections=sections)
    )
    base, tall = measure.rig_measure(rig, {}), measure.rig_measure(rig, {"height": 1.0})
    assert base[0] == pytest.approx(200) and tall[0] == pytest.approx(220)
    assert tall[5] == pytest.approx(base[5] * 1.1) and tall[2] == pytest.approx(base[2])


# ---- the GLB subset ------------------------------------------------------------------------------
def _one_mesh() -> tuple[Any, Any, Any]:
    x, q = tube(around=12, up=4)
    t = mesh.tri_of(q)
    return x, t, mesh.loft_uv([x[i * 12 : (i + 1) * 12] for i in range(4)])


def test_positions_survive_quantising_to_a_sixteen_bit_step() -> None:
    rng = np.random.default_rng(7)
    a = rng.normal(size=(200, 3)) * [0.3, 0.9, 0.2] + [0, 0.9, 0]
    q, scale, off = glb.quantise(a, centred=True)
    assert q.dtype == np.int16 and q.shape == (200, 4) and (q[:, 3] == 0).all()
    assert np.abs(glb.dequantise(q, scale, off) - a).max() <= max(scale) / glb.Q / 2 + 1e-12
    d, dscale, _ = glb.quantise(a * 0.01, centred=False)
    assert np.abs(glb.dequantise(d, dscale) - a * 0.01).max() <= max(dscale) / glb.Q / 2 + 1e-12


def test_a_glb_is_written_and_read_back_with_its_morphs_uvs_and_facts() -> None:
    x, t, uv = _one_mesh()
    w = glb.GlbWriter()
    w.mesh(
        "tube", x, t, uv, {"height": x * 0.1, "tuck": x * [0.02, 0, 0]}, dict(ranges={"a": [0, 12]})
    )
    w.mesh(
        "measure",
        x[:6],
        np.array([[0, 1], [2, 3]]),
        None,
        {"height": x[:6] * 0.1},
        dict(sections={}),
        mode=glb.LINES,
    )
    data = w.to_bytes(dict(sole=0.016))
    assert len(data) % 4 == 0
    got = glb.read_glb(data)
    m = got["meshes"]["tube"]
    assert got["extras"] == {"sole": 0.016} and list(m["targets"]) == ["height", "tuck"]
    assert np.abs(m["x"] - x).max() < 2e-5 and np.abs(m["targets"]["height"] - x * 0.1).max() < 2e-6
    assert (m["index"].reshape(-1, 3) == t).all() and np.abs(m["uv"] - uv).max() < 1e-6
    assert m["extras"]["ranges"] == {"a": [0, 12]} and got["meshes"]["measure"]["mode"] == glb.LINES


def test_the_reader_refuses_what_is_outside_the_subset() -> None:
    x, t, uv = _one_mesh()
    w = glb.GlbWriter()
    w.mesh("tube", x, t, uv, {})
    data = w.to_bytes({})
    with pytest.raises(ValueError, match="version 2 GLB"):
        glb.read_glb(b"nope" + data[4:])
    with pytest.raises(ValueError, match="version 2 GLB"):
        glb.read_glb(data[:-4])
    bad = data.replace(b'"componentType":5122', b'"componentType":5126', 1)
    with pytest.raises(ValueError, match="not in the mannequin's subset"):
        glb.read_glb(bad)
    with pytest.raises(ValueError, match="too many points"):
        glb.GlbWriter().mesh("big", np.zeros((70000, 3)), np.zeros((1, 3), int), None, {})


# ---- the sources: only the table's files, each by its SHA-256, never smplx ----------------------
def test_only_the_tables_files_are_read_and_a_changed_one_is_refused(
    tmp_path: Path, monkeypatch: Any
) -> None:
    sums = fake_clone(tmp_path, core.SOURCES, core.DATA)
    seen: list[str] = []
    real = Path.read_bytes

    def spy(self: Path) -> bytes:
        seen.append(self.relative_to(tmp_path / core.DATA).as_posix())
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", spy)
    h = core.Human(tmp_path, sums)
    h.rest(np.zeros(6))  # reads every target the shape names
    assert set(seen) == set(core.SOURCES) and not [s for s in seen if "smplx" in s]
    assert h.V0.shape == (8, 3) and h.V0[:, 1].max() == pytest.approx(1.0)  # decimetres -> metres
    monkeypatch.undo()
    (tmp_path / core.DATA / "3dobjs/base.obj").write_text("v 0 0 0\n")
    with pytest.raises(core.SourceRefused, match="SHA-256 differs"):
        core.Human(tmp_path, sums)
    with pytest.raises(core.SourceRefused, match="SHA-256 differs"):
        core.Human(tmp_path)  # and never against the real table either


@pytest.mark.parametrize(
    "rel", ["smplx/model.bin", "3dobjs/other.obj", "../LICENSE", "targets/smplx/x.target.gz"]
)
def test_a_file_outside_the_table_is_never_opened(tmp_path: Path, rel: str) -> None:
    fake_clone(tmp_path, core.SOURCES, core.DATA)
    with pytest.raises(core.SourceRefused, match="not a source this build reads"):
        core.read_source(
            tmp_path / core.DATA, rel, {rel: "0" * 64} if "smplx" in rel or ".." in rel else None
        )


def test_the_script_names_smplx_only_to_refuse_it_and_reads_through_one_door() -> None:
    for path in sorted((SCRIPTS / "mannequin").glob("*.py")):
        code = path.read_text()
        tree = ast.parse(code)
        strings = [
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        ]
        docs = {
            ast.get_docstring(n)
            for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
        }
        named = [
            s for s in strings if "smplx" in s.lower() and s not in docs and s.strip() not in docs
        ]
        assert named == (["smplx"] if path.name == "core.py" else []), path.name
        if path.name not in ("core.py", "build.py", "glb.py"):
            assert "read_bytes" not in code and "open(" not in code, path.name


def test_every_module_and_function_of_the_script_keeps_its_size() -> None:
    for path in sorted((SCRIPTS / "mannequin").glob("*.py")):
        lines = path.read_text().splitlines()
        assert len(lines) <= 400, path.name
        for node in ast.walk(ast.parse("\n".join(lines))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert (node.end_lineno or 0) - node.lineno + 1 <= 50, (path.name, node.name)
                assert node.returns is not None, (path.name, node.name)
    assert (SCRIPTS / "mannequin" / "requirements-dev.txt").read_text().split()[-2:] == [
        "numpy==2.5.3",
        "scipy==1.18.1",
    ]
    head = (SCRIPTS / "mannequin" / "measure.py").read_text()[:1200]
    assert "Apache License, Version 2.0" in head and "NAVER Corp." in head and "NOTICE" in head


def test_the_builds_template_table_is_the_servers() -> None:
    from jarvis.wardrobe.tryon import model

    assert tuple(build.TEMPLATES) == model.TEMPLATES
    assert {k: tuple(v["variants"]) for k, v in build.TEMPLATES.items() if v["variants"]} == dict(
        model.VARIANTS
    )
    assert build.SOURCE.endswith(core.ANNY_COMMIT) and core.ANNY_COMMIT in build.NOTICE
    assert json.dumps(build.TEMPLATES)  # plain data: it goes into the manifest
