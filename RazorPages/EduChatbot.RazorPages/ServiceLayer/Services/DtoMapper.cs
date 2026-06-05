using System.Collections.Generic;
using System.Linq;
using DataAccessLayer.Models;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    internal static class DtoMapper
    {
        public static SubjectDto ToDto(this Subject subject, bool includeDocuments = true)
        {
            return new SubjectDto
            {
                Id = subject.Id,
                Name = subject.Name,
                Code = subject.Code,
                OrganizationId = subject.OrganizationId,
                OrganizationName = subject.Organization?.Name ?? string.Empty,
                Documents = includeDocuments
                    ? (subject.Documents ?? new List<Document>()).Select(d => d.ToDto(includeSubject: false)).ToList()
                    : new()
            };
        }

        public static DocumentDto ToDto(this Document document, bool includeSubject = true)
        {
            return new DocumentDto
            {
                Id = document.Id,
                FileName = document.FileName,
                FilePath = document.FilePath,
                SubjectId = document.SubjectId,
                Subject = includeSubject && document.Subject != null ? document.Subject.ToDto(includeDocuments: false) : null,
                UploadedByUserId = document.UploadedByUserId,
                UploadedAt = document.UploadedAt,
                IsIndexed = document.IsIndexed,
                ChunkCount = document.ChunkCount,
                IndexStatus = document.IndexStatus,
                IndexMessage = document.IndexMessage,
                IndexedAt = document.IndexedAt
            };
        }

        public static ChatSessionDto ToDto(this ChatSession session)
        {
            return new ChatSessionDto
            {
                Id = session.Id,
                SubjectId = session.SubjectId,
                UserId = session.UserId ?? string.Empty,
                CreatedAt = session.CreatedAt,
                Subject = session.Subject?.ToDto(includeDocuments: false),
                Messages = (session.Messages ?? new List<ChatMessage>()).OrderBy(m => m.Timestamp).Select(m => m.ToDto()).ToList()
            };
        }

        public static ChatMessageDto ToDto(this ChatMessage message)
        {
            return new ChatMessageDto
            {
                Id = message.Id,
                Role = message.Role,
                Content = message.Content,
                SourceDocuments = message.SourceDocuments ?? string.Empty,
                Timestamp = message.Timestamp
            };
        }
    }
}
