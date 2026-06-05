using System.Collections.Generic;
using System.Threading.Tasks;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    public interface IAuditLogService
    {
        Task RecordAsync(string action, string entityType, int? entityId = null, int? subjectId = null, int? organizationId = null, string? summary = null);
        Task RecordForUserAsync(string? actorUserId, string actorEmail, string? actorRole, string action, string entityType, int? entityId = null, int? subjectId = null, int? organizationId = null, string? summary = null);
        Task<List<AuditLogDto>> GetRecentLogsAsync(int take = 80);
        Task<List<SubjectUsageDto>> GetSubjectUsageAsync();
    }
}
