using System;
using System.IO;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using DataAccessLayer.Data;
using Microsoft.AspNetCore.Hosting;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace ServiceLayer.Services
{
    public class DocumentIndexingWorker : BackgroundService
    {
        private readonly IDocumentIndexingQueue _queue;
        private readonly IServiceScopeFactory _scopeFactory;
        private readonly ILogger<DocumentIndexingWorker> _logger;

        public DocumentIndexingWorker(
            IDocumentIndexingQueue queue,
            IServiceScopeFactory scopeFactory,
            ILogger<DocumentIndexingWorker> logger)
        {
            _queue = queue;
            _scopeFactory = scopeFactory;
            _logger = logger;
        }

        protected override async Task ExecuteAsync(CancellationToken stoppingToken)
        {
            while (!stoppingToken.IsCancellationRequested)
            {
                DocumentIndexingJob job;
                try
                {
                    job = await _queue.DequeueAsync(stoppingToken);
                }
                catch (OperationCanceledException)
                {
                    break;
                }

                try
                {
                    await ProcessAsync(job.DocumentId, stoppingToken);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Document indexing job failed for document {DocumentId}", job.DocumentId);
                }
            }
        }

        private async Task ProcessAsync(int documentId, CancellationToken cancellationToken)
        {
            using var scope = _scopeFactory.CreateScope();
            var context = scope.ServiceProvider.GetRequiredService<ApplicationDbContext>();
            var httpClientFactory = scope.ServiceProvider.GetRequiredService<IHttpClientFactory>();
            var environment = scope.ServiceProvider.GetRequiredService<IWebHostEnvironment>();
            var auditLog = scope.ServiceProvider.GetRequiredService<IAuditLogService>();
            var realtime = scope.ServiceProvider.GetRequiredService<IRealtimeNotificationService>();

            var document = await context.Documents.FirstOrDefaultAsync(d => d.Id == documentId, cancellationToken);
            if (document == null)
                return;

            var subjectId = document.SubjectId;
            var fileName = document.FileName;
            var fullPath = Path.Combine(environment.WebRootPath, document.FilePath.TrimStart('/', '\\').Replace('/', Path.DirectorySeparatorChar));

            if (!File.Exists(fullPath))
            {
                await MarkFailedAsync(context, auditLog, realtime, documentId, subjectId, fileName, "Uploaded file was not found.", cancellationToken);
                return;
            }

            document.IndexStatus = "Processing";
            document.IndexMessage = "AI service is extracting, chunking, and embedding this document.";
            await context.SaveChangesAsync(cancellationToken);
            await realtime.DocumentChangedAsync("processing", subjectId, documentId, fileName);

            try
            {
                using var client = httpClientFactory.CreateClient("AiService");
                using var content = new MultipartFormDataContent();
                content.Add(new StringContent(subjectId.ToString()), "subject_id");
                content.Add(new StringContent(document.Id.ToString()), "document_id");
                content.Add(new StringContent(document.FileName), "document_name");

                await using var fs = new FileStream(fullPath, FileMode.Open, FileAccess.Read, FileShare.Read);
                var fileContent = new StreamContent(fs);
                content.Add(fileContent, "file", document.FileName);

                using var response = await client.PostAsync("/api/documents/index", content, cancellationToken);
                if (response.IsSuccessStatusCode)
                {
                    var responseStr = await response.Content.ReadAsStringAsync(cancellationToken);
                    using var jsonDoc = JsonDocument.Parse(responseStr);

                    var chunks = 0;
                    if (jsonDoc.RootElement.TryGetProperty("chunks", out var chunksProp) && chunksProp.TryGetInt32(out var parsedChunks))
                        chunks = parsedChunks;

                    var indexed = jsonDoc.RootElement.TryGetProperty("indexed", out var indexedProp) && indexedProp.GetBoolean();
                    if (indexed)
                    {
                        document.IsIndexed = true;
                        document.ChunkCount = chunks;
                        document.IndexStatus = "Indexed";
                        document.IndexedAt = DateTime.UtcNow;
                        document.IndexMessage = $"Đã đọc và nhúng {chunks} đoạn nội dung.";
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

            context.Update(document);
            await context.SaveChangesAsync(cancellationToken);
            await auditLog.RecordForUserAsync(null, "system", "System", document.IsIndexed ? "UploadIndexed" : "UploadFailed", "Document", document.Id, subjectId, null, $"{document.FileName}: {document.IndexStatus}.");
            await realtime.DocumentChangedAsync(document.IsIndexed ? "indexed" : "failed", subjectId, document.Id, document.FileName);
        }

        private static async Task MarkFailedAsync(
            ApplicationDbContext context,
            IAuditLogService auditLog,
            IRealtimeNotificationService realtime,
            int documentId,
            int subjectId,
            string fileName,
            string message,
            CancellationToken cancellationToken)
        {
            var document = await context.Documents.FirstOrDefaultAsync(d => d.Id == documentId, cancellationToken);
            if (document == null)
                return;

            document.IsIndexed = false;
            document.IndexStatus = "Failed";
            document.IndexMessage = message;
            await context.SaveChangesAsync(cancellationToken);
            await auditLog.RecordForUserAsync(null, "system", "System", "UploadFailed", "Document", document.Id, subjectId, null, $"{fileName}: {message}");
            await realtime.DocumentChangedAsync("failed", subjectId, documentId, fileName);
        }
    }
}
