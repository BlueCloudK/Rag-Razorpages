using System;
using System.Collections.Generic;

namespace ServiceLayer.Models
{
    public class DocumentDto
    {
        public int Id { get; set; }
        public string FileName { get; set; } = string.Empty;
        public string FilePath { get; set; } = string.Empty;
        public int SubjectId { get; set; }
        public SubjectDto? Subject { get; set; }
        public string? UploadedByUserId { get; set; }
        public DateTime UploadedAt { get; set; }
        public bool IsIndexed { get; set; }
        public int ChunkCount { get; set; }
        public string IndexStatus { get; set; } = string.Empty;
        public string? IndexMessage { get; set; }
        public DateTime? IndexedAt { get; set; }
    }

    public class DocumentChunkInspectorDto
    {
        public string DocumentId { get; set; } = string.Empty;
        public int Total { get; set; }
        public int Offset { get; set; }
        public int Limit { get; set; }
        public List<DocumentChunkDto> Chunks { get; set; } = new();
    }

    public class DocumentChunkDto
    {
        public string Id { get; set; } = string.Empty;
        public string Text { get; set; } = string.Empty;
        public DocumentChunkMetadataDto Metadata { get; set; } = new();
        public int EmbeddingDimensions { get; set; }
        public List<double> EmbeddingPreview { get; set; } = new();
    }

    public class DocumentChunkMetadataDto
    {
        public int SubjectId { get; set; }
        public string DocumentId { get; set; } = string.Empty;
        public string DocumentName { get; set; } = string.Empty;
        public int ChunkIndex { get; set; }
        public int ChunkLength { get; set; }
    }
}
