# Running with Visual Studio 2022

This repository has three separate Visual Studio solutions. Open only the variant you want to run.

## Solutions

| Variant | Solution | Default URL |
| --- | --- | --- |
| MVC | `MVC\EduChatbot.MVC\EduChatbot.MVC.slnx` | `http://localhost:5099` |
| Razor Pages | `RazorPages\EduChatbot.RazorPages\EduChatbot.RazorPages.slnx` | `http://localhost:5101` |
| ProductGroup | `ProductGroup\EduChatbot.ProductGroup\EduChatbot.ProductGroup.slnx` | `http://localhost:5102` |

All three solutions contain only these C# projects:

```text
DataAccessLayer
ServiceLayer
PresentationLayer
```

The shared AI backend is outside the solutions:

```text
AIServices\AiService
```

## Setup

1. Install .NET SDK 8.0 or newer.
2. Install Python dependencies:

```powershell
cd D:\Project\PRN222\AIServices\AiService
pip install -r requirements.txt
```

3. Install an Ollama model:

```powershell
ollama pull qwen2.5:3b
```

### Optional: Use Gemini API Instead of Ollama

By default, the Python AI service uses local Ollama. To use Gemini, set environment variables before opening Visual Studio:

```powershell
setx LLM_PROVIDER gemini
setx GEMINI_API_KEY "your-gemini-api-key"
setx GEMINI_MODEL "gemini-2.5-flash"
```

Close and reopen Visual Studio after running `setx`. Keep real API keys out of git.

## Run a Variant

1. Open one `.slnx` file in Visual Studio 2022.
2. Right-click `PresentationLayer`.
3. Select `Set as Startup Project`.
4. Choose the `http` launch profile.
5. Press `F5` or `Ctrl+F5`.

The selected web app starts the shared AI service automatically at:

```text
http://127.0.0.1:8000
```

If Python is not available in `PATH`, set `AiService:PythonExecutable` in the selected app's `PresentationLayer\appsettings.Development.json`.

## ProductGroup Extras

Only ProductGroup includes these additional demo features:

- Dashboard: `http://localhost:5102/Dashboard`
- SignalR hub: `/hubs/product`
- Realtime activity feed for subject, document, and chat events.
- Background Worker Service heartbeat.

## Troubleshooting

- If the web port is already in use, stop the previous `PresentationLayer` or `EduChatbot` process from Visual Studio or Task Manager.
- If chat/upload says AI is unavailable, check the Visual Studio Output window for `[AiService]` logs.
- If package restore fails, run `dotnet restore` on the selected `.slnx`.
