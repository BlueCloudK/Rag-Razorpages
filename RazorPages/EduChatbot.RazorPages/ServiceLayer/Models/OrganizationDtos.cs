using System;
using System.Collections.Generic;

namespace ServiceLayer.Models
{
    public class OrganizationDto
    {
        public int Id { get; set; }
        public string Name { get; set; } = string.Empty;
        public string Slug { get; set; } = string.Empty;
        public string RoleInOrganization { get; set; } = string.Empty;
    }

    public class OrganizationDashboardDto
    {
        public OrganizationDto? Organization { get; set; }
        public SubscriptionStatusDto? Subscription { get; set; }
        public List<SubjectDto> Subjects { get; set; } = new();
        public List<DocumentDto> RecentDocuments { get; set; } = new();
        public int MemberCount { get; set; }
        public int IndexedDocumentCount { get; set; }
        public int ProcessingDocumentCount { get; set; }
        public bool CanManageOrganization { get; set; }
        public bool CanCreateSubject { get; set; }
    }

    public class OrganizationMemberDto
    {
        public int Id { get; set; }
        public string Email { get; set; } = string.Empty;
        public string FullName { get; set; } = string.Empty;
        public string RoleInOrganization { get; set; } = string.Empty;
        public DateTime JoinedAt { get; set; }
    }
}
