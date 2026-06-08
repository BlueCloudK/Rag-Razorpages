using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Net;
using System.Threading.Tasks;
using DataAccessLayer.Data;
using DataAccessLayer.Models;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.EntityFrameworkCore;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    public class DocumentService : IDocumentService
    {
        private readonly ApplicationDbContext _context;
        private readonly IWebHostEnvironment _environment;
        private readonly IHttpClientFactory _httpClientFactory;
        private readonly IAccessControlService _accessControl;
        private readonly ICurrentUserService _currentUser;
        private readonly ISubscriptionService _subscriptionService;
        private readonly IAuditLogService _auditLogService;
        private readonly IRealtimeNotificationService _realtime;

        public DocumentService(
            ApplicationDbContext context,
            IWebHostEnvironment environment,
            IHttpClientFactory httpClientFactory,
            IAccessControlService accessControl,
            ICurrentUserService currentUser,
            ISubscriptionService subscriptionService,
            IAuditLogService auditLogService,
            IRealtimeNotificationService realtime)
        {
            _context = context;
            _environment = environment;
            _httpClientFactory = httpClientFactory;
            _accessControl = accessControl;
            _currentUser = currentUser;
            _subscriptionService = subscriptionService;
            _auditLogService = auditLogService;
            _realtime = realtime;
        }

        public async Task<List<DocumentDto>> GetAllAsync()
        {
            IQueryable<Document> query = _context.Documents.Include(d => d.Subject);

            if (!await _accessControl.IsAdminAsync())
            {
                var userId = _currentUser.UserId;
                query = query.Where(d => _context.SubjectMemberships.Any(m => m.SubjectId == d.SubjectId && m.UserId == userId));
            }

            var documents = await query
                .Include(d => d.Subject)
                .OrderByDescending(d => d.UploadedAt)
                .ToListAsync();
            var result = new List<DocumentDto>();
            foreach (var document in documents)
            {
                var dto = document.ToDto();
                dto.CanDelete = await _accessControl.CanDeleteDocumentAsync(document.SubjectId);
                result.Add(dto);
            }

            return result;
        }

        public async Task<DocumentDto?> GetByIdAsync(int id)
        {
            var document = await _context.Documents
                .Include(d => d.Subject)
                .FirstOrDefaultAsync(d => d.Id == id);

            if (document == null || !await _accessControl.CanViewSubjectAsync(document.SubjectId))
                return null;

            var dto = document.ToDto();
            dto.CanDelete = await _accessControl.CanDeleteDocumentAsync(document.SubjectId);
            return dto;
        }

        public async Task<DocumentChunkInspectorDto?> GetChunkInspectorAsync(int id, int offset = 0, int limit = 8)
        {
            var document = await _context.Documents.FirstOrDefaultAsync(d => d.Id == id);
            if (document == null || !await _accessControl.CanViewSubjectAsync(document.SubjectId))
                return null;

            try
            {
                using var client = _httpClientFactory.CreateClient("AiService");
                var inspector = await ReadChunkInspectorAsync(client, document.Id.ToString(), offset, limit);
                if (inspector is { Total: > 0 })
                    return inspector;

                var fileNameInspector = await ReadChunkInspectorAsync(client, document.FileName, offset, limit);
                if (fileNameInspector is { Total: > 0 })
                    return fileNameInspector;

                return await ReadSubjectChunkInspectorAsync(client, document.SubjectId, offset, limit) ?? fileNameInspector ?? inspector;
            }
            catch
            {
                return null;
            }
        }

        private static async Task<DocumentChunkInspectorDto?> ReadChunkInspectorAsync(HttpClient client, string documentId, int offset, int limit)
        {
            var safeDocumentId = WebUtility.UrlEncode(documentId);
            using var response = await client.GetAsync($"/api/documents/{safeDocumentId}/chunks?offset={Math.Max(offset, 0)}&limit={Math.Clamp(limit, 1, 20)}");
            if (!response.IsSuccessStatusCode)
                return null;

            var json = await response.Content.ReadAsStringAsync();
            return JsonSerializer.Deserialize<DocumentChunkInspectorDto>(json, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
                PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
            });
        }

        private static async Task<DocumentChunkInspectorDto?> ReadSubjectChunkInspectorAsync(HttpClient client, int subjectId, int offset, int limit)
        {
            using var response = await client.GetAsync($"/api/subjects/{subjectId}/chunks?offset={Math.Max(offset, 0)}&limit={Math.Clamp(limit, 1, 20)}");
            if (!response.IsSuccessStatusCode)
                return null;

            var json = await response.Content.ReadAsStringAsync();
            return JsonSerializer.Deserialize<DocumentChunkInspectorDto>(json, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
                PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
            });
        }

        public async Task<DocumentUploadResult> UploadAndIndexAsync(int subjectId, IFormFile file, string? returnUrl)
        {
            var invalid = ValidateFile(file);
            if (invalid != null)
            {
                return new DocumentUploadResult
                {
                    Status = "Failed",
                    Indexed = false,
                    Message = invalid,
                    ReturnUrl = returnUrl
                };
            }

            if (!await _subscriptionService.CanUploadDocumentAsync(subjectId, file.Length))
            {
                return new DocumentUploadResult
                {
                    Status = "Failed",
                    Indexed = false,
                    Message = "You do not have permission or subscription quota to upload this file.",
                    ReturnUrl = returnUrl
                };
            }

            var normalizedFileName = Path.GetFileName(file.FileName).Trim();
            var duplicateNameExists = await _context.Documents
                .AnyAsync(d => d.SubjectId == subjectId && d.FileName == normalizedFileName);
            if (duplicateNameExists)
            {
                return new DocumentUploadResult
                {
                    Status = "Failed",
                    Indexed = false,
                    Message = "This subject already has a document with the same file name. Rename the file or delete the old one before uploading again.",
                    ReturnUrl = returnUrl
                };
            }

            string uploadsFolder = Path.Combine(_environment.WebRootPath, "uploads");
            Directory.CreateDirectory(uploadsFolder);

            string uniqueFileName = Guid.NewGuid() + "_" + normalizedFileName;
            string filePath = Path.Combine(uploadsFolder, uniqueFileName);

            using (var fileStream = new FileStream(filePath, FileMode.Create))
            {
                await file.CopyToAsync(fileStream);
            }

            var document = new Document
            {
                FileName = normalizedFileName,
                FilePath = "/uploads/" + uniqueFileName,
                SubjectId = subjectId,
                UploadedByUserId = _currentUser.UserId,
                UploadedAt = DateTime.UtcNow,
                IsIndexed = false,
                ChunkCount = 0,
                IndexStatus = "Processing",
                IndexMessage = "Đang upload và đọc tài liệu..."
            };

            _context.Documents.Add(document);
            await _context.SaveChangesAsync();
            await _auditLogService.RecordAsync("UploadStarted", "Document", document.Id, subjectId, null, $"Uploaded document metadata for {document.FileName}.");
            await _realtime.DocumentChangedAsync("uploaded", subjectId, document.Id, document.FileName);

            try
            {
                using var client = _httpClientFactory.CreateClient("AiService");
                using var content = new MultipartFormDataContent();
                content.Add(new StringContent(subjectId.ToString()), "subject_id");
                content.Add(new StringContent(document.Id.ToString()), "document_id");
                content.Add(new StringContent(document.FileName), "document_name");

                using var fs = new FileStream(filePath, FileMode.Open, FileAccess.Read);
                var fileContent = new StreamContent(fs);
                fileContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue(file.ContentType);
                content.Add(fileContent, "file", file.FileName);

                using var response = await client.PostAsync("/api/documents/index", content);
                if (response.IsSuccessStatusCode)
                {
                    var responseStr = await response.Content.ReadAsStringAsync();
                    using var jsonDoc = JsonDocument.Parse(responseStr);

                    if (jsonDoc.RootElement.TryGetProperty("chunks", out var chunksProp) && chunksProp.TryGetInt32(out var chunks))
                        document.ChunkCount = chunks;

                    if (jsonDoc.RootElement.TryGetProperty("indexed", out var indexedProp) && indexedProp.GetBoolean())
                    {
                        document.IsIndexed = true;
                        document.IndexStatus = "Indexed";
                        document.IndexedAt = DateTime.UtcNow;
                        document.IndexMessage = $"Đã đọc và nhúng {document.ChunkCount} đoạn nội dung.";
                    }
                    else
                    {
                        document.IsIndexed = false;
                        document.IndexStatus = "Failed";
                        document.IndexMessage = jsonDoc.RootElement.TryGetProperty("message", out var messageProp)
                            ? messageProp.GetString()
                            : "Python AI Service không index được tài liệu.";
                    }
                }
                else
                {
                    document.IsIndexed = false;
                    document.IndexStatus = "Failed";
                    document.IndexMessage = $"AI Service trả lỗi HTTP {(int)response.StatusCode}.";
                }
            }
            catch (Exception ex)
            {
                document.IsIndexed = false;
                document.IndexStatus = "Failed";
                document.IndexMessage = "Không kết nối được AI Service: " + ex.Message;
            }

            _context.Update(document);
            await _context.SaveChangesAsync();
            await _auditLogService.RecordAsync(document.IsIndexed ? "UploadIndexed" : "UploadFailed", "Document", document.Id, subjectId, null, $"{document.FileName}: {document.IndexStatus}.");
            await _realtime.DocumentChangedAsync(document.IsIndexed ? "indexed" : "failed", subjectId, document.Id, document.FileName);

            return new DocumentUploadResult
            {
                Status = document.IndexStatus,
                Indexed = document.IsIndexed,
                Chunks = document.ChunkCount,
                Message = document.IndexMessage ?? "",
                DocumentId = document.Id,
                FileName = document.FileName,
                ReturnUrl = returnUrl
            };
        }

        public async Task<bool> DeleteAsync(int id)
        {
            var document = await _context.Documents.FindAsync(id);
            if (document == null)
                return false;

            if (!await _accessControl.CanDeleteDocumentAsync(document.SubjectId))
                return false;

            var subjectId = document.SubjectId;
            var fileName = document.FileName;
            string fullPath = Path.Combine(_environment.WebRootPath, document.FilePath.TrimStart('/'));
            if (File.Exists(fullPath))
                File.Delete(fullPath);

            try
            {
                using var client = _httpClientFactory.CreateClient("AiService");
                await client.DeleteAsync($"/api/documents/{document.Id}");
                await client.DeleteAsync($"/api/documents/{Uri.EscapeDataString(document.FileName)}");
            }
            catch
            {
                // Deleting DB metadata should still succeed if the AI service is offline.
            }

            _context.Documents.Remove(document);
            await _context.SaveChangesAsync();
            await _auditLogService.RecordAsync("Delete", "Document", id, subjectId, null, $"Deleted document {fileName}.");
            await _realtime.DocumentChangedAsync("deleted", subjectId, id, fileName);
            return true;
        }

        private static string? ValidateFile(IFormFile file)
        {
            if (file == null || file.Length == 0)
                return "Vui lòng chọn một file hợp lệ.";

            var allowedExtensions = new[] { ".pdf", ".docx", ".pptx", ".ppt" };
            var extension = Path.GetExtension(file.FileName).ToLowerInvariant();
            return allowedExtensions.Contains(extension)
                ? null
                : "Chỉ hỗ trợ file PDF, DOCX, PPTX.";
        }
    }
}
