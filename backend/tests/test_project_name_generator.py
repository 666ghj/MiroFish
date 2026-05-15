from unittest.mock import patch, MagicMock
from app.services.project_name_generator import generate_project_name


def test_generate_project_name_returns_string():
    mock_client = MagicMock()
    mock_client.chat.return_value = "Debat Climàtic BCN 2024"
    with patch('app.services.project_name_generator.LLMClient', return_value=mock_client):
        result = generate_project_name("Text sobre el debat climàtic a Barcelona...")
    assert isinstance(result, str)
    assert len(result) > 0


def test_generate_project_name_fallback_on_error():
    mock_client = MagicMock()
    mock_client.chat.side_effect = Exception("LLM error")
    with patch('app.services.project_name_generator.LLMClient', return_value=mock_client):
        result = generate_project_name("Text qualsevol")
    assert result.startswith("Simulació")
