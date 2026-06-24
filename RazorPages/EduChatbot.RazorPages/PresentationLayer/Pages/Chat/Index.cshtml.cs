using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using ServiceLayer.Models;
using ServiceLayer.Services;
using System.Text.Json;

namespace EduChatbot.RazorPages.Pages.Chat;

public class IndexModel : PageModel
{
    private readonly IChatService _chatService;
    private readonly IDocumentService _documentService;
    private readonly ISubjectService _subjectService;
    private readonly IAccessControlService _accessControlService;
    private readonly IHttpClientFactory _httpClientFactory;

    public IndexModel(
        IChatService chatService,
        IDocumentService documentService,
        ISubjectService subjectService,
        IAccessControlService accessControlService,
        IHttpClientFactory httpClientFactory)
    {
        _chatService = chatService;
        _documentService = documentService;
        _subjectService = subjectService;
        _accessControlService = accessControlService;
        _httpClientFactory = httpClientFactory;
    }

    public SubjectDto CurrentSubject { get; private set; } = new();
    public ChatSessionDto CurrentSession { get; private set; } = new();
    public IList<ChatSessionSummaryDto> ChatSessions { get; private set; } = new List<ChatSessionSummaryDto>();
    public int ActiveSessionId { get; private set; }
    public IList<DocumentDto> Documents { get; private set; } = new List<DocumentDto>();
    public IList<SubjectMembershipAdminDto> SubjectMembers { get; private set; } = new List<SubjectMembershipAdminDto>();
    public IList<SubjectMemberOptionDto> AvailableSubjectMembers { get; private set; } = new List<SubjectMemberOptionDto>();
    public string ActiveTab { get; private set; } = "chat";
    public bool CanManageSubject { get; private set; }
    public bool CanUploadDocuments { get; private set; }
    public bool CanDeleteDocuments { get; private set; }
    public bool CanDeleteSubject { get; private set; }

    public async Task<IActionResult> OnGetAsync(int subjectId, int? sessionId, string? tab = null)
    {
        var loaded = await LoadSubjectAsync(subjectId, sessionId, tab);
        return loaded ? Page() : RedirectToPage("/Index");
    }

    public async Task<IActionResult> OnGetAiStatusAsync()
    {
        try
        {
            using var client = _httpClientFactory.CreateClient("AiService");
            using var response = await client.GetAsync("/");
            if (!response.IsSuccessStatusCode)
            {
                return new JsonResult(new
                {
                    ready = false,
                    status = "starting",
                    message = $"AI Engine is still starting. HTTP {(int)response.StatusCode}"
                });
            }

            return new JsonResult(new
            {
                ready = true,
                status = "ready",
                message = "AI Engine is ready"
            });
        }
        catch (Exception ex)
        {
            return new JsonResult(new { ready = false, status = "starting", message = "AI Engine is still starting: " + ex.Message });
        }
    }

    public async Task<IActionResult> OnGetDocumentChunksAsync(int documentId, int offset = 0, int limit = 8)
    {
        var inspector = await _documentService.GetChunkInspectorAsync(documentId, offset, limit);
        if (inspector == null)
            return NotFound(new { message = "Document chunk inspector is not available." });

        return new JsonResult(inspector);
    }

    public async Task<IActionResult> OnGetIndexProgressAsync(int documentId)
    {
        var document = await _documentService.GetByIdAsync(documentId);
        if (document == null)
            return NotFound(new { message = "Document is not available." });

        if (document.IsIndexed)
        {
            return new JsonResult(new
            {
                documentId,
                stage = "indexed",
                active = false,
                percent = 100,
                completed = document.ChunkCount,
                total = document.ChunkCount,
                message = $"Indexed {document.ChunkCount} chunks."
            });
        }

        try
        {
            using var client = _httpClientFactory.CreateClient("AiService");
            using var response = await client.GetAsync($"/api/documents/{documentId}/index-progress");
            var json = await response.Content.ReadAsStringAsync();
            if (!response.IsSuccessStatusCode)
                throw new InvalidOperationException("AI progress endpoint did not return success.");

            using var progress = JsonDocument.Parse(json);
            var root = progress.RootElement;
            return new JsonResult(new
            {
                documentId,
                stage = root.TryGetProperty("stage", out var stage) ? stage.GetString() : document.IndexStatus,
                active = root.TryGetProperty("active", out var active) && active.GetBoolean(),
                percent = root.TryGetProperty("percent", out var percent) && percent.TryGetInt32(out var pct) ? pct : 0,
                completed = root.TryGetProperty("completed", out var completed) && completed.TryGetInt32(out var done) ? done : 0,
                total = root.TryGetProperty("total", out var total) && total.TryGetInt32(out var count) ? count : 0,
                message = root.TryGetProperty("message", out var message) ? message.GetString() : document.IndexMessage
            });
        }
        catch
        {
            return new JsonResult(new
            {
                documentId,
                stage = document.IndexStatus,
                active = document.IndexStatus != "Failed",
                percent = 0,
                completed = 0,
                total = 0,
                message = document.IndexMessage ?? "Document is still queued for indexing."
            });
        }
    }

    public async Task<IActionResult> OnPostSendMessageAsync(int subjectId, string content, int? sessionId, CancellationToken cancellationToken)
    {
        var result = await _chatService.SendMessageAsync(subjectId, content, sessionId, cancellationToken);
        if (!result.Success)
            return new JsonResult(new { success = false, message = result.Message }) { StatusCode = result.StatusCode };

        return new JsonResult(new
        {
            success = true,
            sessionId = result.SessionId,
            user = new { id = result.User?.Id, content = result.User?.Content },
            bot = new { id = result.Bot?.Id, content = result.Bot?.Content, sourceDocuments = result.Bot?.SourceDocuments },
            trace = result.Trace
        });
    }

    public async Task OnPostSendMessageStreamAsync(int subjectId, string content, int? sessionId, CancellationToken cancellationToken)
    {
        Response.Headers.CacheControl = "no-cache";
        Response.Headers.Connection = "keep-alive";
        Response.ContentType = "text/event-stream; charset=utf-8";

        async Task WriteEventAsync(string eventName, object payload)
        {
            await Response.WriteAsync($"event: {eventName}\n", cancellationToken);
            await Response.WriteAsync("data: ", cancellationToken);
            await JsonSerializer.SerializeAsync(Response.Body, payload, cancellationToken: cancellationToken);
            await Response.WriteAsync("\n\n", cancellationToken);
            await Response.Body.FlushAsync(cancellationToken);
        }

        var result = await _chatService.SendMessageStreamAsync(
            subjectId,
            content,
            sessionId,
            async (eventName, payload) => await WriteEventAsync(eventName, payload),
            cancellationToken);

        if (!result.Success)
        {
            await WriteEventAsync("error", new { success = false, message = result.Message, statusCode = result.StatusCode });
            return;
        }

        await WriteEventAsync("final", new
        {
            success = true,
            sessionId = result.SessionId,
            user = new { id = result.User?.Id, content = result.User?.Content },
            bot = new { id = result.Bot?.Id, content = result.Bot?.Content, sourceDocuments = result.Bot?.SourceDocuments },
            trace = result.Trace
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

    public async Task<IActionResult> OnPostAddMemberAsync(int subjectId, string userId, string roleInSubject)
    {
        await _chatService.AddSubjectMemberAsync(subjectId, userId, roleInSubject);
        return RedirectToPage(new { subjectId, tab = "members" });
    }

    public async Task<IActionResult> OnPostUpdateMemberRoleAsync(int subjectId, int membershipId, string roleInSubject)
    {
        await _chatService.UpdateSubjectMemberRoleAsync(subjectId, membershipId, roleInSubject);
        return RedirectToPage(new { subjectId, tab = "members" });
    }

    public async Task<IActionResult> OnPostRemoveMemberAsync(int subjectId, int membershipId)
    {
        await _chatService.RemoveSubjectMemberAsync(subjectId, membershipId);
        return RedirectToPage(new { subjectId, tab = "members" });
    }

    public async Task<IActionResult> OnPostUpdateSubjectAsync(SubjectInput input)
    {
        await _subjectService.UpdateAsync(input);
        return RedirectToPage(new { subjectId = input.Id, tab = "settings" });
    }

    public async Task<IActionResult> OnPostDeleteSubjectAsync(int subjectId)
    {
        await _subjectService.DeleteAsync(subjectId);
        return RedirectToPage("/Index");
    }

    private async Task<bool> LoadSubjectAsync(int subjectId, int? sessionId, string? tab = null)
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
        SubjectMembers = page.SubjectMembers;
        AvailableSubjectMembers = page.AvailableSubjectMembers;
        CanManageSubject = page.CanManageSubject;
        CanUploadDocuments = page.CanUploadDocuments;
        CanDeleteDocuments = page.CanDeleteDocuments;
        CanDeleteSubject = await _accessControlService.IsAdminAsync();
        ActiveTab = NormalizeTab(tab, CanManageSubject);
        return true;
    }

    private static string NormalizeTab(string? tab, bool canManageSubject)
    {
        var value = (tab ?? "chat").Trim().ToLowerInvariant();
        if (canManageSubject && (value == "members" || value == "settings"))
            return value;

        return "chat";
    }
}
