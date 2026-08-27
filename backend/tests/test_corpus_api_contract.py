from pathlib import Path


def test_graph_api_exposes_recent_corpus_generation_and_selection():
    root = Path(__file__).resolve().parents[2]
    graph_api = (root / "backend" / "app" / "api" / "graph.py").read_text()

    assert "'/project/<project_id>/corpus/recent'" in graph_api
    assert "ProjectManager.get_corpus_text(project_id, corpus)" in graph_api
    assert "data.get('corpus', project.active_corpus or 'full')" in graph_api
    assert '"corpus": corpus' in graph_api
