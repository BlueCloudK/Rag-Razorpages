using System;
using System.ComponentModel.DataAnnotations;

namespace DataAccessLayer.Models
{
    public class AuditLog
    {
        [Key]
        public int Id { get; set; }

        [MaxLength(450)]
        public string? ActorUserId { get; set; }

        [MaxLength(256)]
        public string ActorEmail { get; set; } = string.Empty;

        [MaxLength(40)]
        public string ActorRole { get; set; } = string.Empty;

        [MaxLength(80)]
        public string Action { get; set; } = string.Empty;

        [MaxLength(80)]
        public string EntityType { get; set; } = string.Empty;

        public int? EntityId { get; set; }

        public int? SubjectId { get; set; }

        public int? OrganizationId { get; set; }

        [MaxLength(500)]
        public string Summary { get; set; } = string.Empty;

        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    }
}
