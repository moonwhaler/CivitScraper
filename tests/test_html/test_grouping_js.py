"""The gallery's drill-down helpers (js/grouping.js), run with node."""

import json
import os
import shutil
import subprocess

import pytest

GROUPING = os.path.join(
    os.path.dirname(__file__), "..", "..", "civitscraper", "html", "templates", "js", "grouping.js"
)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def run_js(body):
    script = f"const G = require({json.dumps(os.path.abspath(GROUPING))});\n{body}"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


MODELS = """
const M = [
  {name: 'a', type: 'LORA', base_model: 'Krea 2', group_path: ['style'], file_size: 100,
   file_modified: '2026-01-01T00:00:00Z', health: ['update'], preview_image_path: 'a.mp4', is_video: true},
  {name: 'b', type: 'LORA', base_model: 'Krea 2', group_path: ['style', 'anime'], file_size: 50,
   file_modified: '2026-03-01T00:00:00Z', preview_image_path: 'b.jpg'},
  {name: 'c', type: 'LORA', base_model: 'MOSS Image', group_path: [], file_size: 7},
  {name: 'd', type: 'Checkpoint', base_model: 'Krea 2', file_size: 9000},
];
"""


def test_levels_type_then_base_then_folders():
    top = run_js(
        MODELS + "const l = G.buildLevel(M, []); console.log(JSON.stringify("
        "{at: l.at, label: l.label, groups: l.groups.map(g => [g.name, g.models.length]),"
        " total: l.total}));"
    )
    assert top == {
        "at": [],
        "label": "Type",
        "groups": [["LORA", 3], ["Checkpoint", 1]],
        "total": 4,
    }
    base = run_js(
        MODELS + "const l = G.buildLevel(M, ['LORA']); console.log(JSON.stringify("
        "{groups: l.groups.map(g => g.name), direct: l.direct.length, label: l.label}));"
    )
    assert base == {"groups": ["Krea 2", "MOSS Image"], "direct": 0, "label": "Base model"}


def test_a_single_group_is_skipped_and_direct_models_listed():
    # LORA › Krea 2 has only "style": skipped to style, where b's "anime" is a group and a is direct
    level = run_js(
        MODELS + "const l = G.buildLevel(M, ['LORA', 'Krea 2']); console.log("
        "JSON.stringify({at: l.at, asked: l.asked, groups: l.groups.map(g => g.name),"
        " direct: l.direct.map(m => m.name)}));"
    )
    assert level == {
        "at": ["LORA", "Krea 2", "style"],
        "asked": 2,
        "groups": ["anime"],
        "direct": ["a"],
    }
    up = run_js(
        MODELS + "const l = G.buildLevel(M, ['LORA', 'Krea 2', 'style']);"
        " console.log(JSON.stringify(G.parentPath(M, l)));"
    )
    assert up == ["LORA"]  # past the skipped "Krea 2" step


def test_a_path_that_no_longer_exists_falls_back():
    level = run_js(
        MODELS + "const l = G.buildLevel(M.filter(m => m.type === 'LORA'),"
        " ['Checkpoint', 'Krea 2']); console.log(JSON.stringify(l.at));"
    )
    assert level == ["LORA"]  # back to the top, where the only type left is skipped to


def test_tile_stats():
    stats = run_js(
        MODELS + "const s = G.tileStats(M.slice(0, 2)); console.log(JSON.stringify("
        "{count: s.count, size: s.size, newest: s.newest, update: s.health.update,"
        " previews: s.previews.map(m => m.name)}));"
    )
    assert stats == {
        "count": 2,
        "size": 150,
        "newest": "2026-03-01T00:00:00Z",
        "update": 1,
        "previews": ["b", "a"],
    }  # images before videos


def test_groups_sort_by_name_or_best_value():
    order = run_js(
        MODELS + "const l = G.buildLevel(M, []); console.log(JSON.stringify(["
        "G.sortGroups(l.groups, 'name', 'asc').map(g => g.name),"
        "G.sortGroups(l.groups, 'file_modified', 'desc').map(g => g.name)]));"
    )
    assert order == [["Checkpoint", "LORA"], ["LORA", "Checkpoint"]]
