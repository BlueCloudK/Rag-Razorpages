using System;
using System.Collections.Generic;

namespace ServiceLayer.Models
{
    public class ChatSessionDto
    {
        public int Id { get; set; }
        public int SubjectId { get; set; }
        public string UserId { get; set; } = string.Empty;
        public DateTime CreatedAt { get; set; }
        public SubjectDto? Subject { get; set; }
        public List<ChatMessageDto> Messages { get; set; } = new();
    }

    public class ChatSessionSummaryDto
    {
        public int Id { get; set; }
        public int SubjectId { get; set; }
        public string Title { get; set; } = string.Empty;
        public DateTime CreatedAt { get; set; }
        public DateTime? LastMessageAt { get; set; }
        public string LastMessagePreview { get; set; } = string.Empty;
        public int MessageCount { get; set; }
        public bool IsActive { get; set; }
    }

    public class ChatMessageDto
    {
        public int Id { get; set; }
        public string Role { get; set; } = string.Empty;
        public string Content { get; set; } = string.Empty;
        public string SourceDocuments { get; set; } = string.Empty;
        public DateTime Timestamp { get; set; }
    }

    public class ChatPageDto
    {
        public SubjectDto? CurrentSubject { get; set; }
        public ChatSessionDto? CurrentSession { get; set; }
        public List<ChatSessionSummaryDto> ChatSessions { get; set; } = new();
        public int ActiveSessionId { get; set; }
        public List<DocumentDto> CurrentDocuments { get; set; } = new();
        public List<SubjectMembershipAdminDto> SubjectMembers { get; set; } = new();
        public List<SubjectMemberOptionDto> AvailableSubjectMembers { get; set; } = new();
        public bool CanManageSubject { get; set; }
        public bool CanUploadDocuments { get; set; }
        public bool CanDeleteDocuments { get; set; }
        public SubscriptionStatusDto? SubscriptionStatus { get; set; }
    }

    public class SubjectMemberOptionDto
    {
        public string UserId { get; set; } = string.Empty;
        public string Email { get; set; } = string.Empty;
    }

    public class ChatSendResult
    {
        public bool Success { get; set; }
        public int StatusCode { get; set; } = 200;
        public string Message { get; set; } = string.Empty;
        public int SessionId { get; set; }
        public ChatMessageDto? User { get; set; }
        public ChatMessageDto? Bot { get; set; }
    }
}
