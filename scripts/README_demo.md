# Demo сценарій використання

1. Встановити залежності:
   ```bash
   pip install -r requirements.txt
   ```

2. Запустити сервер:
   ```bash
   uvicorn src.app.server:app --reload
   ```

3. Надіслати запит у `/chat`, наприклад через `curl`:
   ```bash
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"session_id": "demo-session-1", "message": "Хочу договір оренди житла"}'
   ```

> Для повної роботи LLM-агента необхідно виставити змінну середовища `OPENAI_API_KEY`.
