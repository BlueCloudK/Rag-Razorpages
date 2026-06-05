using System;
using System.Collections.Generic;

namespace ServiceLayer.Models
{
    public class AuditLogDto
    {
        public int Id { get; set; }
        public string ActorEmail { get; set; } = string.Empty;
        public string ActorRole { get; set; } = string.Empty;
        public string Action { get; set; } = string.Empty;
        public string EntityType { get; set; } = string.Empty;
        public int? EntityId { get; set; }
        public int? SubjectId { get; set; }
        public int? OrganizationId { get; set; }
        public string Summary { get; set; } = string.Empty;
        public DateTime CreatedAt { get; set; }
    }

    public class SubjectUsageDto
    {
        public int SubjectId { get; set; }
        public string SubjectName { get; set; } = string.Empty;
        public string SubjectCode { get; set; } = string.Empty;
        public int QuestionCount { get; set; }
        public int SessionCount { get; set; }
        public DateTime? LastAskedAt { get; set; }
    }

    public class AuditDashboardDto
    {
        public List<AuditLogDto> RecentLogs { get; set; } = new();
        public List<SubjectUsageDto> SubjectUsage { get; set; } = new();
    }
}
