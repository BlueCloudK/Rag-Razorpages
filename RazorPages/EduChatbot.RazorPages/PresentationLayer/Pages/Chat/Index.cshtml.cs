using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using ServiceLayer.Models;
using ServiceLayer.Services;

namespace EduChatbot.RazorPages.Pages.Chat;

public class IndexModel : PageModel
{
    private readonly IChatService _chatService;
    private readonly IDocumentService _documentService;
    private readonly IHttpClientFactory _httpClientFactory;

    public IndexModel(IChatService chatService, IDocumentService documentService, IHttpClientFactory httpClientFactory)
    {
        _chatService = chatService;
        _documentService = documentService;
        _httpClientFactory = httpClientFactory;
    }

    public SubjectDto CurrentSubject { get; private set; } = new();
    public ChatSessionDto CurrentSession { get; private set; } = new();
    public IList<ChatSessionSummaryDto> ChatSessions { get; private set; } = new List<ChatSessionSummaryDto>();
    public int ActiveSessionId { get; private set; }
    public IList<DocumentDto> Documents { get; private set; } = new List<DocumentDto>();
    public bool CanUploadDocuments { get; private set; }
    public bool CanDeleteDocuments { get; private set; }

    public async Task<IActionResult> OnGetAsync(int subjectId, int? sessionId)
    {
        var loaded = await LoadSubjectAsync(subjectId, sessionId);
        return loaded ? Page() : RedirectToPage("/Index");
    }

    public async Task<IActionResult> OnGetAiStatusAsync()
    {
        try
        {
            using var client = _httpClientFactory.CreateClient("AiService");
            using var response = await client.GetAsync("/");
            return new JsonResult(new
            {
                ready = response.IsSuccessStatusCode,
                status = response.IsSuccessStatusCode ? "ready" : "error",
                message = response.IsSuccessStatusCode ? "AI Engine san sang" : $"AI Engine HTTP {(int)response.StatusCode}"
            })
            { StatusCode = response.IsSuccessStatusCode ? 200 : StatusCodes.Status503ServiceUnavailable };
        }
        catch (Exception ex)
        {
            return new JsonResult(new { ready = false, status = "starting", message = "AI Engine chua san sang: " + ex.Message })
            { StatusCode = StatusCodes.Status503ServiceUnavailable };
        }
    }

    public async Task<IActionResult> OnGetDocumentChunksAsync(int documentId, int offset = 0, int limit = 8)
    {
        var inspector = await _documentService.GetChunkInspectorAsync(documentId, offset, limit);
        if (inspector == null)
            return NotFound(new { message = "Document chunk inspector is not available." });

        return new JsonResult(inspector);
    }

    public async Task<IActionResult> OnPostSendMessageAsync(int subjectId, string content, int? sessionId)
    {
        var result = await _chatService.SendMessageAsync(subjectId, content, sessionId);
        if (!result.Success)
            return new JsonResult(new { success = false, message = result.Message }) { StatusCode = result.StatusCode };

        return new JsonResult(new
        {
            success = true,
            sessionId = result.SessionId,
            user = new { id = result.User?.Id, content = result.User?.Content },
            bot = new { id = result.Bot?.Id, content = result.Bot?.Content, sourceDocuments = result.Bot?.SourceDocuments }
        });
    }

    public async Task<IActionResult> OnPostNewSessionAsync(int subjectId)
    {
        var sessionId = await _chatService.CreateSessionAsync(subjectId);
        return RedirectToPage(new { subjectId, sessionId });
    }

    public async Task<IActionResult> OnPostDeleteSessionAsync(int subjectId, int sessionId)
    {
        await _chatService.DeleteSessionAsync(subjectId, sessionId);
        return RedirectToPage(new { subjectId });
    }

    public async Task<IActionResult> OnPostUploadAsync(int subjectId, IFormFile file, int? sessionId)
    {
        var result = await _documentService.UploadAndIndexAsync(subjectId, file, Url.Page("/Chat/Index", new { subjectId, sessionId }));
        if (result.Status == "Failed" && result.DocumentId == 0)
            return BadRequest(new { status = result.Status, indexed = result.Indexed, chunks = result.Chunks, message = result.Message });

        return new JsonResult(new
        {
            status = result.Status,
            indexed = result.Indexed,
            chunks = result.Chunks,
            message = result.Message,
            documentId = result.DocumentId,
            fileName = result.FileName,
            returnUrl = result.ReturnUrl
        });
    }

    public async Task<IActionResult> OnPostDeleteDocumentAsync(int id, int subjectId, int? sessionId)
    {
        await _documentService.DeleteAsync(id);
        return RedirectToPage(new { subjectId, sessionId });
    }

    private async Task<bool> LoadSubjectAsync(int subjectId, int? sessionId)
    {
        var page = await _chatService.GetChatPageAsync(subjectId, sessionId);
        if (page?.CurrentSubject == null)
            return false;

        CurrentSubject = page.CurrentSubject;
        CurrentSession = page.CurrentSession ?? new ChatSessionDto
        {
            Subject = page.CurrentSubject
        };
        ChatSessions = page.ChatSessions;
        ActiveSessionId = page.ActiveSessionId;
        Documents = page.CurrentDocuments;
        CanUploadDocuments = page.CanUploadDocuments;
        CanDeleteDocuments = page.CanDeleteDocuments;
        return true;
    }
}
