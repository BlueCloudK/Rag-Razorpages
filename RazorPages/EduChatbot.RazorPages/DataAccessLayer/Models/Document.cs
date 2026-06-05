using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace DataAccessLayer.Models
{
    public class Document
    {
        [Key]
        public int Id { get; set; }

        [Required]
        [MaxLength(255)]
        public string FileName { get; set; } = string.Empty;

        [Required]
        [MaxLength(500)]
        public string FilePath { get; set; } = string.Empty;

        public int SubjectId { get; set; }
        
        [ForeignKey("SubjectId")]
        public Subject? Subject { get; set; }

        public string? UploadedByUserId { get; set; }

        [ForeignKey("UploadedByUserId")]
        public ApplicationUser? UploadedByUser { get; set; }

        public DateTime UploadedAt { get; set; } = DateTime.UtcNow;

        public bool IsIndexed { get; set; } = false;

        public int ChunkCount { get; set; } = 0;

        [MaxLength(50)]
        public string IndexStatus { get; set; } = "Pending";

        [MaxLength(1000)]
        public string? IndexMessage { get; set; }

        public DateTime? IndexedAt { get; set; }
    }
}
